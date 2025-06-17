# mcp_service/main.py

import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.endpoints import tasks
from app.core.settings import settings
from app.utils.logger import logger
from app.db.session import init_db  
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager for application lifespan events.
    This is executed once on startup and once on shutdown.
    """
    logger.rule(f"Starting {settings.PROJECT_NAME}", style="green")
    
    logger.info("Initializing database...")
    await init_db()
    logger.success("Database initialized successfully.")
    
    try:
        os.makedirs(settings.FILE_STORAGE_PATH, exist_ok=True)
        logger.info(f"File storage path checked/created at: {settings.FILE_STORAGE_PATH}")
    except OSError as e:
        logger.error(f"Could not create file storage directory: {e}")

    yield

    logger.rule(f"Stopping {settings.PROJECT_NAME}", style="red")

app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Include the tasks router
app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"])

@app.get("/", tags=["Health Check"])
async def read_root():
    """
    Root endpoint to check if the service is running.
    """
    logger.info("Health check endpoint was called.")
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)