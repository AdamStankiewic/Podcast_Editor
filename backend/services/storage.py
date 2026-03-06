"""
Storage service for managing job artifacts and idempotency
Provides filesystem-based storage with automatic directory creation
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from backend.models import Job, JobStatus, JobArtifacts


class StorageService:
    """Manages job artifacts on filesystem"""

    def __init__(self, base_path: str = "./data"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def get_job_dir(self, job_id: str) -> Path:
        """Get job-specific directory, create if not exists"""
        job_dir = self.base_path / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def get_artifact_path(self, job_id: str, artifact_name: str) -> Path:
        """Get path to specific artifact"""
        return self.get_job_dir(job_id) / artifact_name

    def artifact_exists(self, job_id: str, artifact_name: str) -> bool:
        """Check if artifact exists and is valid (non-empty)"""
        path = self.get_artifact_path(job_id, artifact_name)
        return path.exists() and path.stat().st_size > 0

    def save_job_state(self, job: Job):
        """Save job state to JSON file (atomic write to prevent corruption on crash)"""
        job_dir = self.get_job_dir(job.id)
        state_file = job_dir / "job_state.json"

        # Update timestamp
        job.updated_at = datetime.utcnow()

        # Write to a temp file first, then atomically rename to prevent partial writes
        fd, tmp_path = tempfile.mkstemp(dir=job_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(job.model_dump(mode='json'), f, indent=2, default=str)
            os.replace(tmp_path, state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load_job_state(self, job_id: str) -> Optional[Job]:
        """Load job state from JSON file"""
        state_file = self.get_job_dir(job_id) / "job_state.json"

        if not state_file.exists():
            return None

        try:
            with state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return Job(**data)
        except Exception as e:
            print(f"Error loading job state for {job_id}: {e}")
            return None

    def get_all_jobs(self) -> list[Job]:
        """Get all jobs from storage"""
        jobs = []
        for job_dir in self.base_path.iterdir():
            if job_dir.is_dir():
                job = self.load_job_state(job_dir.name)
                if job:
                    jobs.append(job)

        # Sort by created_at descending
        jobs.sort(key=lambda x: x.created_at, reverse=True)
        return jobs

    def add_log(self, job_id: str, message: str, level: str = "INFO"):
        """Add log entry to job"""
        job = self.load_job_state(job_id)
        if job:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [{level}] {message}"
            job.logs.append(log_entry)
            self.save_job_state(job)

            # Also save to separate log file
            log_file = self.get_job_dir(job_id) / "pipeline.log"
            with log_file.open("a", encoding="utf-8") as f:
                f.write(log_entry + "\n")

    def update_progress(self, job_id: str, step: str, completed: int, total: int = 7, message: str = ""):
        """Update job progress"""
        job = self.load_job_state(job_id)
        if job:
            job.progress.current_step = step
            job.progress.completed_steps = completed
            job.progress.total_steps = total
            job.progress.percent = (completed / total) * 100
            job.progress.current_message = message
            self.save_job_state(job)

    def mark_step_complete(self, job_id: str, artifact_name: str, artifact_path: str):
        """Mark a pipeline step as complete by saving artifact reference"""
        job = self.load_job_state(job_id)
        if job:
            # Update artifacts - support both legacy and multi-language patterns
            if artifact_name == "original_video":
                job.artifacts.original_video = artifact_path
            elif artifact_name == "transcript_de":
                job.artifacts.transcript_de = artifact_path
            # Legacy single-language artifacts
            elif artifact_name == "transcript_pl":
                job.artifacts.translations["pl"] = artifact_path
            elif artifact_name == "ssml_pl":
                job.artifacts.ssml_files["pl"] = artifact_path
            elif artifact_name == "tts_audio":
                job.artifacts.tts_audio["pl"] = artifact_path
            elif artifact_name == "final_video":
                job.artifacts.final_videos["pl"] = artifact_path
            # Multi-language artifacts (transcript_{lang}, tts_{lang}, etc.)
            elif artifact_name.startswith("transcript_") and artifact_name != "transcript_de":
                lang = artifact_name.split("_")[1]
                job.artifacts.translations[lang] = artifact_path
            elif artifact_name.startswith("ssml_"):
                lang = artifact_name.split("_")[1]
                job.artifacts.ssml_files[lang] = artifact_path
            elif artifact_name.startswith("tts_"):
                lang = artifact_name.split("_")[1]
                job.artifacts.tts_audio[lang] = artifact_path
            elif artifact_name.startswith("enhanced_"):
                lang = artifact_name.split("_")[1]
                job.artifacts.enhanced_audio[lang] = artifact_path
            elif artifact_name.startswith("final_"):
                lang = artifact_name.split("_")[1]
                job.artifacts.final_videos[lang] = artifact_path

            self.save_job_state(job)

    def cleanup_job(self, job_id: str):
        """Delete all job data"""
        job_dir = self.get_job_dir(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir)


# Global instance
storage = None


def get_storage() -> StorageService:
    """Get global storage instance"""
    global storage
    if storage is None:
        storage = StorageService()
    return storage
