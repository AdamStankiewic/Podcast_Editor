"""
Data models for Podcast Language Converter
Defines job states, artifacts, and progress tracking
"""
from enum import Enum
from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field
from pathlib import Path


class JobStatus(str, Enum):
    """Job processing states"""
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSLATING = "TRANSLATING"
    GENERATING_TTS = "GENERATING_TTS"
    ENHANCING_AUDIO = "ENHANCING_AUDIO"
    RENDERING = "RENDERING"
    DONE = "DONE"
    ERROR = "ERROR"


class JobArtifacts(BaseModel):
    """Artifacts generated during pipeline execution"""
    # Shared artifacts (language-independent)
    original_video: Optional[str] = None
    transcript_de: Optional[str] = None  # Original German transcript

    # Per-language artifacts (Dict[language_code, file_path])
    translations: Dict[str, str] = Field(default_factory=dict)  # e.g., {"pl": "path/to/pl.txt", "fr": ...}
    ssml_files: Dict[str, str] = Field(default_factory=dict)
    tts_audio: Dict[str, str] = Field(default_factory=dict)
    enhanced_audio: Dict[str, str] = Field(default_factory=dict)
    final_videos: Dict[str, str] = Field(default_factory=dict)


class JobProgress(BaseModel):
    """Detailed progress information"""
    current_step: str
    total_steps: int = 7
    completed_steps: int = 0
    percent: float = 0.0
    current_message: str = ""


class Job(BaseModel):
    """Main job model"""
    id: str
    url: str
    status: JobStatus = JobStatus.QUEUED
    progress: JobProgress = Field(default_factory=lambda: JobProgress(current_step="queued", completed_steps=0))
    artifacts: JobArtifacts = Field(default_factory=JobArtifacts)
    logs: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    # Metadata
    video_id: Optional[str] = None
    video_title: Optional[str] = None
    video_duration: Optional[float] = None

    # Options
    languages: List[str] = Field(default_factory=lambda: ["pl"])  # Output languages (pl, fr, en)
    enable_background_music: bool = False  # Add background music to final video

    class Config:
        use_enum_values = True


class CreateJobRequest(BaseModel):
    """Request to create new jobs"""
    urls: List[str] = Field(..., min_items=1, description="List of YouTube URLs")
    languages: List[str] = Field(default=["pl"], description="Output languages (pl, fr, en)")
    enable_background_music: bool = Field(default=False, description="Add background music (loop.wav) to final video")


class JobResponse(BaseModel):
    """API response for job status"""
    job: Job


class JobListResponse(BaseModel):
    """API response for job list"""
    jobs: List[Job]
    total: int


class LogEntry(BaseModel):
    """Log entry for WebSocket streaming"""
    job_id: str
    timestamp: datetime
    level: str  # INFO, WARNING, ERROR
    message: str
    step: Optional[str] = None
