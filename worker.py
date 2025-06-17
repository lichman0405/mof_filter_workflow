# mcp_service/worker.py

from app.tasks.celery_app import celery_app

# This file is the entry point for the Celery worker.
# To run the worker, you would execute the following command in your terminal:
# celery -A worker.celery_app worker --loglevel=info
# For Windows, it's recommended to use the solo pool:
# celery -A worker.celery_app worker --loglevel=info -P solo