# mcp_service/app/api/endpoints/tasks.py

import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession
from celery import group, chain

from app.core.settings import settings
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
    summary="Create a new batch screening task from uploaded files"
)
async def create_batch_task(
    task_data: schemas.TaskCreate,
    db: AsyncSession = Depends(get_session)
):
    """
    Creates a new batch screening task based on a set of previously uploaded files.
    """
    logger.info(f"Received new batch task request for upload session: {task_data.upload_session_id}")

    # --- 1. Locate and validate the uploaded files directory on the server ---
    materials_directory = os.path.join(settings.FILE_STORAGE_PATH, task_data.upload_session_id)
    logger.info(f"Scanning server directory: {materials_directory}")
    
    if not os.path.isdir(materials_directory):
        raise HTTPException(status_code=400, detail=f"Upload session directory not found: {task_data.upload_session_id}")
    
    cif_files = [f for f in os.listdir(materials_directory) if f.endswith('.cif')]
    if not cif_files:
        raise HTTPException(status_code=400, detail=f"No .cif files found in upload session: {task_data.upload_session_id}")
    logger.info(f"Found {len(cif_files)} CIF files to process.")

    # --- 2. LLM Interaction ---
    llm_client = LLMClient()
    try:
        llm_generated_rules = await llm_client.get_structured_rules_from_prompt(user_prompt=task_data.filtering_prompt)
    except Exception as e:
        logger.error(f"LLM processing failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to process prompt with LLM: {e}")

    # --- 3. Database Operations ---
    db_batch_task = models.BatchTask(
        task_name=task_data.task_name,
        filtering_prompt=task_data.filtering_prompt,
        llm_generated_rules=llm_generated_rules,
        materials_directory=materials_directory,
        status=models.BatchStatus.PENDING
    )
    db.add(db_batch_task)
    
    for cif_file in cif_files:
        db_sub_task = models.SubTask(
            batch_task=db_batch_task,
            original_cif_path=os.path.join(materials_directory, cif_file),
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
        raise HTTPException(status_code=500, detail="Database operation failed.")

    # --- 4. Trigger Celery Workflow (with robust error handling) ---
    try:
        logger.info(f"Building and dispatching Celery workflow for batch_id: {db_batch_task.batch_id}")
        analysis_group = group(initial_analysis_task.s(sub.id) for sub in db_batch_task.sub_tasks)
        filtering_task_signature = run_first_filtering_task.s(db_batch_task.id)
        workflow = chain(analysis_group, filtering_task_signature)
        workflow.apply_async()
        
        logger.success(f"Successfully dispatched workflow for batch_id: {db_batch_task.batch_id}")
        
        # If dispatch is successful, update the status to PROCESSING
        db_batch_task.status = models.BatchStatus.PROCESSING
        db.add(db_batch_task)
        await db.commit()

    except Exception as e:
        # If dispatching to Celery fails, we must mark the task as FAILED.
        logger.error(f"FATAL: Failed to dispatch Celery workflow for batch_id {db_batch_task.batch_id}. Error: {e}")
        db_batch_task.status = models.BatchStatus.FAILED
        db.add(db_batch_task)
        await db.commit()
        # Raise an exception to inform the client that something went wrong.
        raise HTTPException(status_code=500, detail="Failed to dispatch background workflow.")

    return db_batch_task
