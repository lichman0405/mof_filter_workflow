# mcp_service/app/api/endpoints/tasks.py
# The module is for managing batch screening tasks in a materials science application.
# Author: Shibo Li
# Date: 2025-06-16
# Version: 0.1.0

import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from celery import group, chain

from app.db import models
from app.db.session import get_session
from app.schemas import task as schemas
from app.utils.logger import logger
from app.services.llm_service import LLMClient
from app.tasks.analysis_tasks import initial_analysis_task, run_first_filtering_task

router = APIRouter()

@router.post(
    "/batch-screening-tasks",
    response_model=schemas.BatchTaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new batch screening task"
)
async def create_batch_task(
    task_data: schemas.TaskCreate,
    db: AsyncSession = Depends(get_session)
):
    """
    Creates a new batch screening task. This involves:
    1.  Calling an LLM to parse the filtering prompt.
    2.  Scanning the provided directory for CIF files.
    3.  Creating entries in the database for the batch task and all sub-tasks.
    4.  Dispatching a Celery workflow to run analysis and then filtering.
    """
    logger.info(f"Received new batch task request: '{task_data.task_name}'")

    # LLM client initialization and prompt processing
    logger.info("Initializing LLM client to process filtering prompt.")
    llm_client = LLMClient()
    try:
        llm_generated_rules = await llm_client.get_structured_rules_from_prompt(
            user_prompt=task_data.filtering_prompt
        )
    except Exception as e:
        logger.error(f"LLM processing failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to process prompt with LLM: {e}")

    # cif file scanning
    logger.info(f"Scanning directory: {task_data.materials_directory}")
    if not os.path.isdir(task_data.materials_directory):
        raise HTTPException(status_code=400, detail=f"Directory not found: {task_data.materials_directory}")
    
    cif_files = [f for f in os.listdir(task_data.materials_directory) if f.endswith('.cif')]
    if not cif_files:
        raise HTTPException(status_code=400, detail=f"No .cif files found in directory: {task_data.materials_directory}")
    logger.info(f"Found {len(cif_files)} CIF files to process.")

    # Database operations
    logger.info("Creating database entries for the batch task and sub-tasks.")
    db_batch_task = models.BatchTask(
        task_name=task_data.task_name,
        filtering_prompt=task_data.filtering_prompt,
        llm_generated_rules=llm_generated_rules,
        materials_directory=task_data.materials_directory,
        status=models.BatchStatus.PENDING
    )
    db.add(db_batch_task)
    
    for cif_file in cif_files:
        db_sub_task = models.SubTask(
            batch_task=db_batch_task,
            original_cif_path=os.path.join(task_data.materials_directory, cif_file),
            status=models.SubTaskStatus.PENDING
        )
        db.add(db_sub_task)
    
    try:
        await db.commit()
        await db.refresh(db_batch_task)
        for sub_task in db_batch_task.sub_tasks:
            await db.refresh(sub_task)
        logger.success(f"Successfully created batch task with ID: {db_batch_task.batch_id}")
    except Exception as e:
        await db.rollback()
        logger.error(f"Database error: Failed to create batch task. Details: {e}")
        raise HTTPException(status_code=500, detail="Database operation failed.")

    # Celery workflow dispatch
    logger.info(f"Building Celery workflow for batch_id: {db_batch_task.batch_id}")

    analysis_group = group(
        initial_analysis_task.s(sub_task.id) for sub_task in db_batch_task.sub_tasks
    )
    filtering_task_signature = run_first_filtering_task.s(db_batch_task.id)
    workflow = chain(analysis_group, filtering_task_signature)
    workflow.apply_async()
    
    logger.success(f"Successfully dispatched workflow for batch_id: {db_batch_task.batch_id}")
    
    db_batch_task.status = models.BatchStatus.PROCESSING
    db.add(db_batch_task)
    await db.commit()
    logger.info(f"Batch task {db_batch_task.batch_id} status updated to PROCESSING.")

    return db_batch_task