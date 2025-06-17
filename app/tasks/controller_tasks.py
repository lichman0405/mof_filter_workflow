# mcp_service/app/tasks/controller_tasks.py

import psycopg2
from sqlmodel import select, Session
from sqlalchemy import create_engine
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.db import models
from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import run_second_filtering_task
from app.utils.logger import logger


sync_db_url = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2").replace("sqlite+aiosqlite", "sqlite")
sync_engine = create_engine(sync_db_url)

def get_sync_session():
    """Provides a synchronous database session."""
    return Session(sync_engine)


@celery_app.task
def workflow_controller_task():
    """
    A periodic task that acts as a workflow controller.
    This version uses synchronous database calls for stability within Celery.
    """
    logger.info("Controller Task: Running workflow check (sync mode)...")
    db = get_sync_session()
    try:
        # Find all batch tasks that are currently in a processing state
        query = select(models.BatchTask).where(
            models.BatchTask.status.in_([models.BatchStatus.PROCESSING])
        ).options(selectinload(models.BatchTask.sub_tasks))
        
        active_batch_tasks = db.exec(query).all()

        for batch in active_batch_tasks:
            check_for_second_filtering(db, batch)
            check_for_completion(db, batch)
    finally:
        db.close()


def check_for_second_filtering(db: Session, batch: models.BatchTask):
    """
    Checks if a batch is ready for the second round of filtering (sync version).
    """
    sub_tasks = batch.sub_tasks
    if not sub_tasks:
        return

    waiting_status = models.SubTaskStatus.SECOND_FILTERING
    final_statuses = {
        models.SubTaskStatus.XTB_OPTIMIZATION,
        models.SubTaskStatus.COMPLETED,
        models.SubTaskStatus.FILTERED_OUT,
        models.SubTaskStatus.FAILED,
    }
    
    all_ready = all(
        sub.status == waiting_status for sub in sub_tasks if sub.status not in final_statuses
    )
    
    is_any_awaiting = any(sub.status == waiting_status for sub in sub_tasks)

    if all_ready and is_any_awaiting:
        logger.success(f"Controller: Batch {batch.id} is ready for second filtering. Triggering now.")
        batch.status = models.BatchStatus.AWAITING_SECOND_FILTER
        db.add(batch)
        db.commit()
        run_second_filtering_task.delay(batch.id)


def check_for_completion(db: Session, batch: models.BatchTask):
    """
    Checks if a batch task is fully completed (sync version).
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
        db.commit()
