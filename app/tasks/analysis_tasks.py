# mcp_service/app/tasks/analysis_tasks.py
# The module contains the Celery tasks for performing various analysis steps on materials.
# Author: Shibo Li
# Date: 2025-06-16
# Version: 0.1.0


import asyncio
import os
from functools import wraps
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.settings import settings
from app.db.session import AsyncSessionLocal
from app.db import models
from app.tasks.celery_app import celery_app
from app.services.worker_clients import ZeoClient, FileConverterClient, MaceClient, XTBClient
from app.utils.logger import logger


def async_task_runner(f):
    """
    A decorator to handle the boilerplate of running an async function
    inside a synchronous Celery task. It manages the event loop and
    database session.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

def sub_task_lifecycle(initial_status: models.SubTaskStatus, final_status: models.SubTaskStatus):
    """
    A decorator to manage the lifecycle of a sub-task: fetching it from the DB,
    updating its status, and handling exceptions.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(sub_task_id: int, *args, **kwargs):
            logger.info(f"Starting task '{func.__name__}' for sub_task_id: {sub_task_id}")
            async with AsyncSessionLocal() as db:
                sub_task = None
                try:
                    query = select(models.SubTask).options(selectinload(models.SubTask.batch_task)).where(models.SubTask.id == sub_task_id)
                    result = await db.execute(query)
                    sub_task = result.scalar_one_or_none()
                    if not sub_task:
                        logger.error(f"SubTask {sub_task_id} not found.")
                        return

                    await _update_status(db, sub_task, initial_status)
                    
                    # Execute the core task logic
                    await func(db=db, sub_task=sub_task, *args, **kwargs)
                    
                    await _update_status(db, sub_task, final_status)
                    logger.success(f"Completed task '{func.__name__}' for sub_task {sub_task_id}.")

                except Exception as e:
                    logger.error(f"Error during '{func.__name__}' for sub_task {sub_task_id}: {e}")
                    if sub_task: 
                        async with AsyncSessionLocal() as db_fail: 
                            sub_task_fail = await db_fail.get(models.SubTask, sub_task_id)
                            if sub_task_fail:
                                sub_task_fail.error_message = str(e)
                                await _update_status(db_fail, sub_task_fail, models.SubTaskStatus.FAILED)
        return wrapper
    return decorator


async def _update_status(db: AsyncSession, sub_task: models.SubTask, status: models.SubTaskStatus):
    sub_task.status = status
    db.add(sub_task)
    await db.commit()
    await db.refresh(sub_task)


def _evaluate_rules(rules: dict, properties: dict) -> bool:
    if not rules.get("rules"): return True
    for rule in rules["rules"]:
        metric, condition, target_value = rule.get("metric"), rule.get("condition"), rule.get("value")
        actual_value = None
        if metric == "pore_diameter": actual_value = properties.get("pore_diameter", {}).get("included_diameter")
        elif metric == "channel_dimension": actual_value = properties.get("channel_analysis", {}).get("dimension")
        elif metric == "surface_area": actual_value = properties.get("surface_area", {}).get("asa_mass")
        elif metric == "accessible_volume": actual_value = properties.get("accessible_volume", {}).get("av_fraction")
        elif metric == "probe_volume": actual_value = properties.get("probe_volume", {}).get("poav_fraction")
        if actual_value is None: continue
        try:
            if condition == "greater_than" and not float(actual_value) > float(target_value): return False
            elif condition == "less_than" and not float(actual_value) < float(target_value): return False
            elif condition == "equals" and not float(actual_value) == float(target_value): return False
        except (ValueError, TypeError): continue
    return True


@celery_app.task
@async_task_runner
@sub_task_lifecycle(models.SubTaskStatus.INITIAL_ANALYSIS, models.SubTaskStatus.FIRST_FILTERING)
async def initial_analysis_task(db: AsyncSession, sub_task: models.SubTask):
    sub_task_dir = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), str(sub_task.sub_task_id))
    os.makedirs(sub_task_dir, exist_ok=True)
    cif_filename = os.path.basename(sub_task.original_cif_path)
    with open(sub_task.original_cif_path, 'rb') as f:
        cif_content = f.read()
    zeo_client = ZeoClient(task_storage_path=sub_task_dir)
    sub_task.results = await zeo_client.get_all_properties(cif_content, cif_filename)


@celery_app.task
@async_task_runner
@sub_task_lifecycle(models.SubTaskStatus.MACE_OPTIMIZATION, models.SubTaskStatus.POST_MACE_ANALYSIS)
async def mace_optimization_task(db: AsyncSession, sub_task: models.SubTask):
    converter, mace = FileConverterClient(), MaceClient()
    cif_path = sub_task.original_cif_path
    with open(cif_path, 'rb') as f:
        cif_content = f.read()
    xyz_content = await converter.convert_file(cif_content, os.path.basename(cif_path))
    optimized_xyz_content = await mace.optimize_structure(xyz_content)
    output_filename = f"{sub_task.sub_task_id}_post_mace.xyz"
    output_path = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), output_filename)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(optimized_xyz_content)
    current_results = dict(sub_task.results)
    current_results.setdefault('MACE', {})['optimized_xyz_path'] = output_path
    sub_task.results = current_results
    post_mace_analysis_task.delay(sub_task.id) # Trigger next task


@celery_app.task
@async_task_runner
@sub_task_lifecycle(models.SubTaskStatus.POST_MACE_ANALYSIS, models.SubTaskStatus.SECOND_FILTERING)
async def post_mace_analysis_task(db: AsyncSession, sub_task: models.SubTask):
    optimized_xyz_path = sub_task.results.get("MACE", {}).get("optimized_xyz_path")
    if not optimized_xyz_path or not os.path.exists(optimized_xyz_path):
        raise FileNotFoundError(f"Optimized XYZ file not found at {optimized_xyz_path}")
    converter = FileConverterClient()
    with open(optimized_xyz_path, 'rb') as f:
        xyz_content = f.read()
    cif_content_post_mace = await converter.convert_file(xyz_content, os.path.basename(optimized_xyz_path))
    sub_task_dir = os.path.dirname(optimized_xyz_path)
    post_mace_cif_filename = f"{sub_task.sub_task_id}_post_mace.cif"
    post_mace_cif_path = os.path.join(sub_task_dir, post_mace_cif_filename)
    with open(post_mace_cif_path, 'wb') as f:
        f.write(cif_content_post_mace)
    zeo_client = ZeoClient(task_storage_path=sub_task_dir)
    properties = await zeo_client.get_all_properties(cif_content_post_mace, post_mace_cif_filename)
    current_results = dict(sub_task.results)
    current_results.setdefault('post_mace_analysis', {})['properties'] = properties
    current_results['post_mace_analysis']['cif_path'] = post_mace_cif_path
    sub_task.results = current_results


@celery_app.task
@async_task_runner
@sub_task_lifecycle(models.SubTaskStatus.XTB_OPTIMIZATION, models.SubTaskStatus.COMPLETED)
async def xtb_optimization_task(db: AsyncSession, sub_task: models.SubTask):
    xyz_input_path = sub_task.results.get("MACE", {}).get("optimized_xyz_path")
    if not xyz_input_path or not os.path.exists(xyz_input_path):
        raise FileNotFoundError(f"Input XYZ file for XTB not found at {xyz_input_path}")
    with open(xyz_input_path, 'rb') as f:
        xyz_content = f.read()
    xtb_client = XTBClient()
    final_xyz_content = await xtb_client.optimize_structure(xyz_content)
    final_filename = f"{sub_task.sub_task_id}_final_xtb.xyz"
    final_path = os.path.join(settings.FILE_STORAGE_PATH, str(sub_task.batch_task.batch_id), final_filename)
    with open(final_path, 'wb') as f:
        f.write(final_xyz_content)
    current_results = dict(sub_task.results)
    current_results.setdefault('XTB', {})['final_xyz_path'] = final_path
    sub_task.results = current_results
    sub_task.final_optimized_path = final_path


@celery_app.task
@async_task_runner
async def run_first_filtering_task(batch_task_id: int):
    logger.info(f"Starting first filtering for batch_task_id: {batch_task_id}")
    async with AsyncSessionLocal() as db:
        query = select(models.BatchTask).options(selectinload(models.BatchTask.sub_tasks)).where(models.BatchTask.id == batch_task_id)
        result = await db.execute(query)
        batch_task = result.scalar_one_or_none()
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
            for sub_task in survivors: mace_optimization_task.delay(sub_task.id)
        else:
            batch_task.status = models.BatchStatus.COMPLETED
            await db.commit()


@celery_app.task
@async_task_runner
async def run_second_filtering_task(batch_task_id: int):
    logger.info(f"Starting SECOND filtering for batch_task_id: {batch_task_id}")
    async with AsyncSessionLocal() as db:
        query = select(models.BatchTask).options(selectinload(models.BatchTask.sub_tasks)).where(models.BatchTask.id == batch_task_id)
        result = await db.execute(query)
        batch_task = result.scalar_one_or_none()
        if not batch_task: return
        rules, final_survivors = batch_task.llm_generated_rules, []
        for sub_task in batch_task.sub_tasks:
            if sub_task.status == models.SubTaskStatus.SECOND_FILTERING:
                post_mace_properties = sub_task.results.get("post_mace_analysis", {}).get("properties", {})
                if _evaluate_rules(rules, post_mace_properties):
                    await _update_status(db, sub_task, models.SubTaskStatus.XTB_OPTIMIZATION)
                    final_survivors.append(sub_task)
                else:
                    await _update_status(db, sub_task, models.SubTaskStatus.FILTERED_OUT)
        if final_survivors:
            for sub_task in final_survivors: xtb_optimization_task.delay(sub_task.id)
        else:
            batch_task.status = models.BatchStatus.COMPLETED
            await db.commit()

