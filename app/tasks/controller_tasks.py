# mcp_service/app/tasks/controller_tasks.py
# The module for managing workflow control tasks in the application.
# Author: Shibo Li
# Date: 2025-06-17
# Version: 0.1.0

import asyncio
from sqlmodel import select
from sqlalchemy.orm import selectinload
from app.db.session import AsyncSessionLocal
from app.db import models
from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import run_second_filtering_task
from app.utils.logger import logger

@celery_app.task
def workflow_controller_task():
    """
    A periodic task that acts as a workflow controller.
    It checks the status of ongoing batch tasks and triggers next steps.
    """
    asyncio.run(check_and_advance_workflows())

async def check_and_advance_workflows():
    """
    The core async logic for the workflow controller.
    """
    logger.info("Controller Task: Running workflow check...")
    async with AsyncSessionLocal() as db:
        # Find all batch tasks that are currently in a processing state
        query = select(models.BatchTask).where(
            models.BatchTask.status.in_([
                models.BatchStatus.PROCESSING,
            ])
        ).options(selectinload(models.BatchTask.sub_tasks))
        
        result = await db.execute(query)
        active_batch_tasks = result.scalars().all()

        for batch in active_batch_tasks:
            await check_for_second_filtering(db, batch)
            await check_for_completion(db, batch)

async def check_for_second_filtering(db, batch: models.BatchTask):
    """
    Checks if a batch is ready for the second round of filtering.
    """
    sub_tasks = batch.sub_tasks
    if not sub_tasks:
        return

    # Define statuses that are "stuck" waiting for the second filter
    # and statuses that are already past this point or have failed.
    waiting_status = models.SubTaskStatus.SECOND_FILTERING
    final_statuses = {
        models.SubTaskStatus.XTB_OPTIMIZATION,
        models.SubTaskStatus.COMPLETED,
        models.SubTaskStatus.FILTERED_OUT,
        models.SubTaskStatus.FAILED,
    }
    
    # Check if every task that isn't already finished is waiting for the second filter.
    all_ready_for_filtering = all(
        sub.status == waiting_status for sub in sub_tasks if sub.status not in final_statuses
    )
    
    # And ensure that there's at least one task actually waiting.
    is_any_task_awaiting_filter = any(
        sub.status == waiting_status for sub in sub_tasks
    )

    if all_ready_for_filtering and is_any_task_awaiting_filter:
        logger.success(f"Controller: Batch {batch.id} is ready for second filtering. Triggering now.")
        # Update status to prevent re-triggering
        batch.status = models.BatchStatus.AWAITING_SECOND_FILTER
        db.add(batch)
        await db.commit()
        run_second_filtering_task.delay(batch.id)

async def check_for_completion(db, batch: models.BatchTask):
    """
    Checks if a batch task is fully completed.
    """
    final_statuses = {
        models.SubTaskStatus.COMPLETED,
        models.SubTaskStatus.FILTERED_OUT,
        models.SubTaskStatus.FAILED,
    }
    
    all_finished = all(sub.status in final_statuses for sub in batch.sub_tasks)

    if all_finished and batch.status != models.BatchStatus.COMPLETED:
        logger.success(f"Controller: All sub-tasks for batch {batch.id} are finished. Marking batch as COMPLETED.")
        batch.status = models.BatchStatus.COMPLETED
        db.add(batch)
        await db.commit()
