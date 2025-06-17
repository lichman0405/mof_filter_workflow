# mcp_service/app/api/endpoints/tasks.py
# The module is for managing batch screening tasks in a materials science application.
# Author: Shibo Li
# Date: 2025-06-16
# Version: 0.1.0

# mcp_service/app/api/endpoints/tasks.py

import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

# Imports are now simpler
from app.core.settings import settings
from app.db import models
from app.db.session import get_session
from app.schemas import task as schemas
from app.utils.logger import logger
from app.services.llm_service import LLMClient
# Import the new launcher task
from app.tasks.analysis_tasks import launch_main_workflow

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
    Creates a new batch screening task. This endpoint now only handles
    database creation and triggers a single, simple background task.
    """
    # Steps 1, 2, and 3 are the same: Validate, call LLM, create DB records
    # ... (code for LLM and file scanning is unchanged)
    logger.info(f"Received new batch task request for upload session: {task_data.upload_session_id}")
    materials_directory = os.path.join(settings.FILE_STORAGE_PATH, task_data.upload_session_id)
    if not os.path.isdir(materials_directory):
        raise HTTPException(status_code=400, detail=f"Upload session directory not found: {task_data.upload_session_id}")
    cif_files = [f for f in os.listdir(materials_directory) if f.endswith('.cif')]
    if not cif_files:
        raise HTTPException(status_code=400, detail=f"No .cif files found in upload session: {task_data.upload_session_id}")
    
    llm_client = LLMClient()
    try:
        llm_generated_rules = await llm_client.get_structured_rules_from_prompt(user_prompt=task_data.filtering_prompt)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to process prompt with LLM: {e}")

    db_batch_task = models.BatchTask(
        task_name=task_data.task_name,
        filtering_prompt=task_data.filtering_prompt,
        llm_generated_rules=llm_generated_rules,
        materials_directory=materials_directory,
        status=models.BatchStatus.PENDING
    )
    db.add(db_batch_task)
    for cif_file in cif_files:
        db.add(models.SubTask(
            batch_task=db_batch_task,
            original_cif_path=os.path.join(materials_directory, cif_file),
            status=models.SubTaskStatus.PENDING
        ))
    
    try:
        await db.commit()
        await db.refresh(db_batch_task)
        logger.success(f"Successfully created batch task with ID: {db_batch_task.batch_id}")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database operation failed.")

    # --- 4. Trigger a SINGLE launcher task ---
    try:
        # The API's only interaction with Celery is now this single, robust call.
        launch_main_workflow.delay(db_batch_task.id)
        logger.success(f"Successfully dispatched launcher task for batch_id: {db_batch_task.batch_id}")
        
        # Update status to PROCESSING
        db_batch_task.status = models.BatchStatus.PROCESSING
        db.add(db_batch_task)
        await db.commit()
        
    except Exception as e:
        # This error is now much less likely, but we handle it just in case.
        logger.error(f"FATAL: Failed to dispatch launcher task for batch_id {db_batch_task.id}. Error: {e}")
        db_batch_task.status = models.BatchStatus.FAILED
        db.add(db_batch_task)
        await db.commit()
        raise HTTPException(status_code=500, detail="Failed to dispatch background workflow.")

    return db_batch_task
