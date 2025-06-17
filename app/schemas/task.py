# mcp_service/app/schemas/task.py

import uuid
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

# Import status enums from our database models
from app.db.models import BatchStatus, SubTaskStatus

# --- Base Schemas ---
# These are the fundamental building blocks for other schemas.

class TaskBase(BaseModel):
    """Base schema for a task, containing common fields."""
    task_name: Optional[str] = Field(None, description="An optional descriptive name for the task.")


# --- Schemas for Creating Tasks ---

class TaskCreate(TaskBase):
    """
    Schema for the request body when creating a new batch screening task.
    This defines the data the user must provide.
    """
    materials_directory: str = Field(..., description="The absolute path to the directory containing candidate CIF files.")
    filtering_prompt: str = Field(..., description="The user's filtering criteria in natural language.")


# --- Schemas for Reading/Responding with Task Data ---

class SubTaskRead(BaseModel):
    """Schema for representing a single sub-task in API responses."""
    sub_task_id: uuid.UUID
    status: SubTaskStatus
    original_cif_path: str
    error_message: Optional[str] = None

    class Config:
        # Pydantic v1 compatibility for orm_mode
        # For Pydantic v2, this would be: model_config = {"from_attributes": True}
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