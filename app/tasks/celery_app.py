# mcp_service/app/tasks/celery_app.py

from celery import Celery
from app.core.settings import settings

# Create a Celery instance
celery_app = Celery(
    "tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        'app.tasks.analysis_tasks',
        'app.tasks.controller_tasks'
    ]
)

celery_app.conf.update(
    task_track_started=True,
)

celery_app.conf.beat_schedule = {
    'run-workflow-controller-every-60-seconds': {
        'task': 'app.tasks.controller_tasks.workflow_controller_task',
        'schedule': 120.0,  
    },
}
