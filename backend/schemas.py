"""API response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class TaskSubmitted(BaseModel):
    task_id: str
    status: str = "PENDING"
    message: str = "QC task submitted"


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    stage: str | None = None
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
