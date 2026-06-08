"""
Workflow state and result classes.

Provides common result classes for all orchestrators.
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum
from datetime import datetime


@dataclass
class WorkflowResult:
    """
    Base result class for workflow execution.
    
    All orchestrators should return this or a subclass.
    """
    success: bool
    video_id: str
    video_url: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    FETCHING_STORY = "fetching_story"
    GENERATING_SCRIPT = "generating_script"
    GENERATING_IMAGES = "generating_images"
    GENERATING_AUDIO = "generating_audio"
    CREATING_VIDEO = "creating_video"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class WorkflowState:
    """
    State of workflow execution for Reddit stories.
    
    Used for resuming interrupted workflows.
    """
    workflow_id: str
    story_id: str
    status: WorkflowStatus
    current_step: str
    script_path: Optional[str] = None
    images_paths: Optional[list] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            "workflow_id": self.workflow_id,
            "story_id": self.story_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WorkflowState':
        """Create from dictionary"""
        return cls(
            workflow_id=data["workflow_id"],
            story_id=data["story_id"],
            status=WorkflowStatus(data["status"]),
            current_step=data["current_step"],
            error=data.get("error"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
        )
