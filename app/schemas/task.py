# mcp_service/app/schemas/task.py

import uuid
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# Import status enums from our database models
from app.db.models import BatchStatus, SubTaskStatus

class TaskBase(BaseModel):
    """Base schema for a task, containing common fields."""
    task_name: Optional[str] = Field(None, description="An optional descriptive name for the task.")

class TaskCreate(TaskBase):
    """
    Schema for creating a new batch task, referencing a previous file upload session.
    """
    upload_session_id: str = Field(..., description="The unique session ID returned by the /upload endpoint.")
    filtering_prompt: str = Field(..., description="The user's filtering criteria in natural language.")

class SubTaskRead(BaseModel):
    """Schema for representing a single sub-task in API responses."""
    sub_task_id: uuid.UUID
    status: SubTaskStatus
    original_cif_path: str
    error_message: Optional[str] = None

    class Config:
        orm_mode = True

class BatchTaskRead(TaskBase):
    """
    Schema for the basic API response after creating or retrieving a batch task.
    """
    batch_id: uuid.UUID
    status: BatchStatus
    created_at: datetime
    updated_at: datetime
    filtering_prompt: str

    class Config:
        orm_mode = True

class BatchTaskReadWithSubTasks(BatchTaskRead):
    """
    A more detailed schema for a batch task, including all its associated sub-tasks.
    """
    sub_tasks: List[SubTaskRead] = []