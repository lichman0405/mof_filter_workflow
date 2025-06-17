# mcp_service/main.py

import uvicorn
import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.endpoints import tasks, files
from app.core.settings import settings
from app.utils.logger import logger
from app.db.session import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan event handler for the FastAPI application.
    This function initializes the database and checks/creates the file storage directory
    """
    logger.rule(f"Starting {settings.PROJECT_NAME}", style="green")
    
    # Initialize the database
    logger.info("Initializing database...")
    await init_db()
    logger.success("Database initialized successfully.")

    # Ensure the root file storage directory exists
    os.makedirs(settings.FILE_STORAGE_PATH, exist_ok=True)
    logger.info(f"File storage path checked/created at: {settings.FILE_STORAGE_PATH}")

    yield

    logger.rule(f"Stopping {settings.PROJECT_NAME}", style="red")

# Create FastAPI application instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Mount the files and tasks routers with different path prefixes
app.include_router(files.router, prefix="/api/v1/files", tags=["Files"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"])

@app.get("/", tags=["Health Check"])
async def read_root():
    """
    Root endpoint to check if the service is running.
    """
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)