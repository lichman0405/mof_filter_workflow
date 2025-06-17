# mcp_service/app/tasks/analysis_tasks.py
# The module contains the Celery tasks for performing various analysis steps on materials.
# Author: Shibo Li
# Date: 2025-06-16
# Version: 0.1.0

import asyncio
import os
from functools import wraps
from sqlmodel import select, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession
from celery import group, chain

from app.core.settings import settings
from app.db import models
from app.db.session import AsyncSessionLocal
from app.tasks.celery_app import celery_app
from app.services.worker_clients import ZeoClient, FileConverterClient, MaceClient, XTBClient
from app.utils.logger import logger

# --- Reusable Decorator ---
def async_task_runner(f):
    """A decorator to handle running an async function inside a sync Celery task."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

# --- Helper Functions ---
async def _update_status(db: AsyncSession, sub_task: models.SubTask, status: models.SubTaskStatus):
    """Helper function to update a sub-task's status and commit to the DB."""
    sub_task.status = status
    db.add(sub_task)
    await db.commit()
    await db.refresh(sub_task)

def _evaluate_rules(rules: dict, properties: dict) -> bool:
    """Evaluates if a material's properties satisfy the given set of rules."""
    if not rules.get("rules"):
        return True
    for rule in rules["rules"]:
        metric, condition, target_value = rule.get("metric"), rule.get("condition"), rule.get("value")
        actual_value = None

        if metric == "pore_diameter":
            actual_value = properties.get("pore_diameter", {}).get("included_diameter")
        elif metric == "channel_dimension":
            actual_value = properties.get("channel_analysis", {}).get("dimension")
        elif metric == "surface_area":
            actual_value = properties.get("surface_area", {}).get("asa_mass")
        elif metric == "accessible_volume":
            actual_value = properties.get("accessible_volume", {}).get("av_fraction")
        elif metric == "probe_volume":
            actual_value = properties.get("probe_volume", {}).get("poav_fraction")
        
        if actual_value is None:
            continue

        try:
            if condition == "greater_than":
                if not float(actual_value) > float(target_value): return False
            elif condition == "less_than":
                if not float(actual_value) < float(target_value): return False
            elif condition == "equals":
                if not float(actual_value) == float(target_value): return False
        except (ValueError, TypeError):
            continue
            
    return True

# --- Celery Task Definitions ---

@celery_app.task
def launch_main_workflow(batch_task_id: int):
    """This task is triggered by the API to build and launch the main workflow."""
    sync_db_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2").replace("sqlite+aiosqlite", "sqlite")
    sync_engine = create_engine(sync_db_url)
    with Session(sync_engine) as db:
        logger.info(f"Launcher task: Building workflow for batch_id: {batch_task_id}...")
        sub_task_ids = db.exec(select(models.SubTask.id).where(models.SubTask.batch_task_id == batch_task_id)).all()

        if not sub_task_ids:
            logger.error(f"No sub-tasks found for batch_id {batch_task_id}. Aborting.")
            return

        analysis_group = group(initial_analysis_task.s(id) for id in sub_task_ids)
        # Use .si() for an immutable signature, which ignores the result of the previous task in the chain.
        filtering_task_signature = run_first_filtering_task.si(batch_task_id)
        workflow = chain(analysis_group, filtering_task_signature)
        
        workflow.apply_async()
        logger.success(f"Launcher task: Successfully launched main workflow for batch_id: {batch_task_id}")

@celery_app.task
@async_task_runner
async def initial_analysis_task(sub_task_id: int):
    """Celery task to perform initial analysis on a single MOF material."""
    logger.info(f"Starting initial analysis for sub_task_id: {sub_task_id}")
    async with AsyncSessionLocal() as db:
        try:
            query = select(models.SubTask).options(selectinload(models.SubTask.batch_task)).where(models.SubTask.id == sub_task_id)
            sub_task = await db.scalar(query)
            if not sub_task: return
            
            await _update_status(db, sub_task, models.SubTaskStatus.INITIAL_ANALYSIS)
            
            sub_task_dir = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), str(sub_task.sub_task_id))
            os.makedirs(sub_task_dir, exist_ok=True)
            
            with open(sub_task.original_cif_path, 'rb') as f:
                cif_content = f.read()
            
            zeo_client = ZeoClient(task_storage_path=sub_task_dir)
            sub_task.results = await zeo_client.get_all_properties(cif_content, os.path.basename(sub_task.original_cif_path))
            
            await _update_status(db, sub_task, models.SubTaskStatus.FIRST_FILTERING)
        except Exception as e:
            logger.error(f"Error in initial_analysis_task for sub_task {sub_task_id}: {e}")
            async with AsyncSessionLocal() as db_fail:
                sub_task_fail = await db_fail.get(models.SubTask, sub_task_id)
                if sub_task_fail:
                    sub_task_fail.error_message = str(e)
                    await _update_status(db_fail, sub_task_fail, models.SubTaskStatus.FAILED)

@celery_app.task
@async_task_runner
async def run_first_filtering_task(batch_task_id: int):
    """Celery task to filter materials after initial analysis."""
    logger.info(f"Starting first filtering for batch_task_id: {batch_task_id}")
    async with AsyncSessionLocal() as db:
        query = select(models.BatchTask).options(selectinload(models.BatchTask.sub_tasks)).where(models.BatchTask.id == batch_task_id)
        batch_task = await db.scalar(query)
        if not batch_task: return

        rules, survivors = batch_task.llm_generated_rules, []
        for sub_task in batch_task.sub_tasks:
            if sub_task.status == models.SubTaskStatus.FIRST_FILTERING:
                if _evaluate_rules(rules, sub_task.results):
                    await _update_status(db, sub_task, models.SubTaskStatus.MACE_OPTIMIZATION)
                    survivors.append(sub_task)
                else:
                    await _update_status(db, sub_task, models.SubTaskStatus.FILTERED_OUT)
        
        if survivors:
            logger.info(f"Dispatching MACE optimization for {len(survivors)} survivors.")
            for sub_task in survivors: mace_optimization_task.delay(sub_task.id)
        else:
            logger.warning(f"No survivors after first filtering for batch {batch_task_id}.")
            batch_task.status = models.BatchStatus.COMPLETED
            db.add(batch_task)
            await db.commit()

@celery_app.task
@async_task_runner
async def mace_optimization_task(sub_task_id: int):
    """Celery task to perform MACE optimization and trigger re-analysis."""
    logger.info(f"Starting MACE optimization for sub_task_id: {sub_task_id}")
    async with AsyncSessionLocal() as db:
        try:
            query = select(models.SubTask).options(selectinload(models.SubTask.batch_task)).where(models.SubTask.id == sub_task_id)
            sub_task = await db.scalar(query)
            if not sub_task: return

            await _update_status(db, sub_task, models.SubTaskStatus.MACE_OPTIMIZATION)
            
            converter, mace = FileConverterClient(), MaceClient()
            with open(sub_task.original_cif_path, 'rb') as f:
                cif_content = f.read()
            xyz_content = await converter.convert_file(cif_content, os.path.basename(sub_task.original_cif_path))
            optimized_xyz = await mace.optimize_structure(xyz_content)
            
            output_filename = f"{sub_task.sub_task_id}_post_mace.xyz"
            output_path = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), output_filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(optimized_xyz)
            
            current_results = dict(sub_task.results)
            current_results.setdefault('MACE', {})['optimized_xyz_path'] = output_path
            sub_task.results = current_results
            
            await _update_status(db, sub_task, models.SubTaskStatus.POST_MACE_ANALYSIS)
            post_mace_analysis_task.delay(sub_task.id)
        except Exception as e:
            logger.error(f"Error in mace_optimization_task for sub_task {sub_task_id}: {e}")
            async with AsyncSessionLocal() as db_fail:
                sub_task_fail = await db_fail.get(models.SubTask, sub_task_id)
                if sub_task_fail:
                    sub_task_fail.error_message = str(e)
                    await _update_status(db_fail, sub_task_fail, models.SubTaskStatus.FAILED)

@celery_app.task
@async_task_runner
async def post_mace_analysis_task(sub_task_id: int):
    """Celery task to perform Zeo++ analysis AFTER MACE optimization."""
    logger.info(f"Starting post-MACE analysis for sub_task_id: {sub_task_id}")
    async with AsyncSessionLocal() as db:
        try:
            query = select(models.SubTask).options(selectinload(models.SubTask.batch_task)).where(models.SubTask.id == sub_task_id)
            sub_task = await db.scalar(query)
            if not sub_task: return

            opt_path = sub_task.results.get("MACE", {}).get("optimized_xyz_path")
            if not opt_path or not os.path.exists(opt_path):
                raise FileNotFoundError(f"Optimized XYZ not found at {opt_path}")
            
            with open(opt_path, 'rb') as f:
                xyz_content = f.read()
            
            converter = FileConverterClient()
            cif_post_mace = await converter.convert_file(xyz_content, os.path.basename(opt_path))
            
            sub_task_dir = os.path.dirname(opt_path)
            cif_filename = f"{sub_task.sub_task_id}_post_mace.cif"
            cif_path = os.path.join(sub_task_dir, cif_filename)
            with open(cif_path, 'wb') as f:
                f.write(cif_post_mace)
            
            zeo_client = ZeoClient(task_storage_path=sub_task_dir)
            properties = await zeo_client.get_all_properties(cif_post_mace, cif_filename)
            
            current_results = dict(sub_task.results)
            current_results.setdefault('post_mace_analysis', {})['properties'] = properties
            current_results['post_mace_analysis']['cif_path'] = cif_path
            sub_task.results = current_results
            
            await _update_status(db, sub_task, models.SubTaskStatus.SECOND_FILTERING)
        except Exception as e:
            logger.error(f"Error in post_mace_analysis_task for sub_task {sub_task_id}: {e}")
            async with AsyncSessionLocal() as db_fail:
                sub_task_fail = await db_fail.get(models.SubTask, sub_task_id)
                if sub_task_fail:
                    sub_task_fail.error_message = str(e)
                    await _update_status(db_fail, sub_task_fail, models.SubTaskStatus.FAILED)

@celery_app.task
@async_task_runner
async def run_second_filtering_task(batch_task_id: int):
    """Celery task to perform the SECOND round of filtering."""
    logger.info(f"Starting SECOND filtering for batch_task_id: {batch_task_id}")
    async with AsyncSessionLocal() as db:
        query = select(models.BatchTask).options(selectinload(models.BatchTask.sub_tasks)).where(models.BatchTask.id == batch_task_id)
        batch_task = await db.scalar(query)
        if not batch_task: return
        
        rules, final_survivors = batch_task.llm_generated_rules, []
        for sub_task in batch_task.sub_tasks:
            if sub_task.status == models.SubTaskStatus.SECOND_FILTERING:
                post_mace_props = sub_task.results.get("post_mace_analysis", {}).get("properties", {})
                if _evaluate_rules(rules, post_mace_props):
                    await _update_status(db, sub_task, models.SubTaskStatus.XTB_OPTIMIZATION)
                    final_survivors.append(sub_task)
                else:
                    await _update_status(db, sub_task, models.SubTaskStatus.FILTERED_OUT)
        
        if final_survivors:
            logger.info(f"Dispatching final XTB optimization for {len(final_survivors)} survivors.")
            for sub_task in final_survivors: xtb_optimization_task.delay(sub_task.id)
        else:
            logger.warning(f"No survivors after final filtering for batch {batch_task_id}.")
            batch_task.status = models.BatchStatus.COMPLETED
            db.add(batch_task)
            await db.commit()

@celery_app.task
@async_task_runner
async def xtb_optimization_task(sub_task_id: int):
    """Performs the final XTB optimization."""
    logger.info(f"Starting FINAL XTB optimization for sub_task_id: {sub_task_id}")
    async with AsyncSessionLocal() as db:
        try:
            query = select(models.SubTask).options(selectinload(models.SubTask.batch_task)).where(models.SubTask.id == sub_task_id)
            sub_task = await db.scalar(query)
            if not sub_task: return

            await _update_status(db, sub_task, models.SubTaskStatus.XTB_OPTIMIZATION)
            
            xyz_path = sub_task.results.get("MACE", {}).get("optimized_xyz_path")
            if not xyz_path or not os.path.exists(xyz_path):
                raise FileNotFoundError(f"Input XYZ for XTB not found at {xyz_path}")
            
            with open(xyz_path, 'rb') as f:
                xyz_content = f.read()
            
            xtb_client = XTBClient()
            final_xyz = await xtb_client.optimize_structure(xyz_content)
            
            final_filename = f"{sub_task.sub_task_id}_final_xtb.xyz"
            final_path = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), final_filename)
            with open(final_path, 'wb') as f:
                f.write(final_xyz)
            
            current_results = dict(sub_task.results)
            current_results.setdefault('XTB', {})['final_xyz_path'] = final_path
            sub_task.results = current_results
            sub_task.final_optimized_path = final_path
            
            await _update_status(db, sub_task, models.SubTaskStatus.COMPLETED)
        except Exception as e:
            logger.error(f"Error in xtb_optimization_task for sub_task {sub_task_id}: {e}")
            async with AsyncSessionLocal() as db_fail:
                sub_task_fail = await db_fail.get(models.SubTask, sub_task_id)
                if sub_task_fail:
                    sub_task_fail.error_message = str(e)
                    await _update_status(db_fail, sub_task_fail, models.SubTaskStatus.FAILED)