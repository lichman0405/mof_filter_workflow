# mcp_service/app/db/models.py

import enum
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import func
from sqlmodel import Field, Relationship, SQLModel, JSON, Column


# Enum Definitions for Task Statuses
class BatchStatus(str, enum.Enum):
    """Status for the entire batch task."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    AWAITING_SECOND_FILTER = "AWAITING_SECOND_FILTER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"

class SubTaskStatus(str, enum.Enum):
    """Status for each individual material (sub-task)."""
    PENDING = "PENDING"
    INITIAL_ANALYSIS = "INITIAL_ANALYSIS"
    FIRST_FILTERING = "FIRST_FILTERING"
    MACE_OPTIMIZATION = "MACE_OPTIMIZATION"
    POST_MACE_ANALYSIS = "POST_MACE_ANALYSIS"
    SECOND_FILTERING = "SECOND_FILTERING"
    XTB_OPTIMIZATION = "XTB_OPTIMIZATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    FILTERED_OUT = "FILTERED_OUT"


# SQLModel Definitions for Database Models
class BatchTask(SQLModel, table=True):
    __tablename__ = "batch_tasks"
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True, unique=True, nullable=False)
    task_name: Optional[str] = Field(default=None, index=True)
    status: BatchStatus = Field(default=BatchStatus.PENDING, nullable=False)
    filtering_prompt: str = Field()
    llm_generated_rules: dict = Field(sa_column=Column(JSON))
    materials_directory: str = Field()
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": func.now()}, nullable=False)
    sub_tasks: List["SubTask"] = Relationship(back_populates="batch_task")


class SubTask(SQLModel, table=True):
    __tablename__ = "sub_tasks"
    id: Optional[int] = Field(default=None, primary_key=True)
    sub_task_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True, unique=True, nullable=False)
    batch_task_id: int = Field(foreign_key="batch_tasks.id")
    status: SubTaskStatus = Field(default=SubTaskStatus.PENDING, nullable=False)
    original_cif_path: str = Field()
    final_optimized_path: Optional[str] = Field(default=None)
    results: dict = Field(default={}, sa_column=Column(JSON))
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": func.now()}, nullable=False)
    batch_task: BatchTask = Relationship(back_populates="sub_tasks")

