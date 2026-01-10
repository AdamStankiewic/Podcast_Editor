"""
Unit tests for pipeline idempotency
Tests that pipeline steps can be safely re-run without side effects
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from backend.services.storage import StorageService
from backend.models import Job, JobStatus


class TestStorageIdempotency:
    """Test storage service idempotency"""

    def setup_method(self):
        """Setup temporary storage"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = StorageService(base_path=self.temp_dir)

    def teardown_method(self):
        """Cleanup"""
        shutil.rmtree(self.temp_dir)

    def test_artifact_exists_check(self):
        """Test artifact existence checking"""
        job_id = "test-job-1"

        # Initially should not exist
        assert self.storage.artifact_exists(job_id, "test.txt") is False

        # Create artifact
        artifact_path = self.storage.get_artifact_path(job_id, "test.txt")
        artifact_path.write_text("test content")

        # Now should exist
        assert self.storage.artifact_exists(job_id, "test.txt") is True

    def test_empty_file_not_valid(self):
        """Test that empty files are not considered valid artifacts"""
        job_id = "test-job-2"

        # Create empty file
        artifact_path = self.storage.get_artifact_path(job_id, "empty.txt")
        artifact_path.write_text("")

        # Empty file should not be considered valid
        assert self.storage.artifact_exists(job_id, "empty.txt") is False

    def test_job_state_persistence(self):
        """Test that job state persists across loads"""
        job = Job(
            id="test-job-3",
            url="https://youtube.com/watch?v=test",
            status=JobStatus.DOWNLOADING,
            video_id="test123"
        )

        # Save job
        self.storage.save_job_state(job)

        # Load job
        loaded_job = self.storage.load_job_state(job.id)

        assert loaded_job is not None
        assert loaded_job.id == job.id
        assert loaded_job.status == JobStatus.DOWNLOADING
        assert loaded_job.video_id == "test123"

    def test_multiple_save_load_cycles(self):
        """Test that job can be saved and loaded multiple times"""
        job = Job(
            id="test-job-4",
            url="https://youtube.com/watch?v=test",
            status=JobStatus.QUEUED
        )

        # Save, load, modify, save again
        self.storage.save_job_state(job)

        loaded = self.storage.load_job_state(job.id)
        loaded.status = JobStatus.DOWNLOADING
        self.storage.save_job_state(loaded)

        loaded2 = self.storage.load_job_state(job.id)
        assert loaded2.status == JobStatus.DOWNLOADING

    def test_mark_step_complete_idempotent(self):
        """Test that marking step complete multiple times is safe"""
        job = Job(id="test-job-5", url="https://youtube.com/test")
        self.storage.save_job_state(job)

        # Mark step complete multiple times
        self.storage.mark_step_complete(job.id, "transcript_de", "/path/to/transcript.txt")
        self.storage.mark_step_complete(job.id, "transcript_de", "/path/to/transcript.txt")

        # Should still have correct artifact path
        loaded = self.storage.load_job_state(job.id)
        assert loaded.artifacts.transcript_de == "/path/to/transcript.txt"

    def test_log_accumulation(self):
        """Test that logs accumulate correctly"""
        job = Job(id="test-job-6", url="https://youtube.com/test")
        self.storage.save_job_state(job)

        # Add logs
        self.storage.add_log(job.id, "Log 1", "INFO")
        self.storage.add_log(job.id, "Log 2", "INFO")
        self.storage.add_log(job.id, "Log 3", "ERROR")

        # Load and check logs
        loaded = self.storage.load_job_state(job.id)
        assert len(loaded.logs) == 3
        assert "Log 1" in loaded.logs[0]
        assert "Log 2" in loaded.logs[1]
        assert "ERROR" in loaded.logs[2]


class TestPipelineStepIdempotency:
    """Test that pipeline steps are idempotent"""

    def setup_method(self):
        """Setup temporary storage"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = StorageService(base_path=self.temp_dir)

    def teardown_method(self):
        """Cleanup"""
        shutil.rmtree(self.temp_dir)

    def test_skip_existing_artifact(self):
        """Test that pipeline steps skip when artifact exists"""
        job_id = "test-job-7"

        # Create existing artifact
        artifact_path = self.storage.get_artifact_path(job_id, "original.mp4")
        artifact_path.write_text("fake video data")

        # Check that artifact exists (would skip processing)
        assert self.storage.artifact_exists(job_id, "original.mp4") is True

    def test_progress_updates_idempotent(self):
        """Test that progress updates can be called multiple times"""
        job = Job(id="test-job-8", url="https://youtube.com/test")
        self.storage.save_job_state(job)

        # Update progress multiple times
        self.storage.update_progress(job.id, "downloading", 1, message="Starting...")
        self.storage.update_progress(job.id, "downloading", 1, message="In progress...")
        self.storage.update_progress(job.id, "downloading", 1, message="Almost done...")

        # Should have latest message
        loaded = self.storage.load_job_state(job.id)
        assert loaded.progress.current_message == "Almost done..."
        assert loaded.progress.completed_steps == 1


class TestConcurrentAccess:
    """Test concurrent access scenarios"""

    def setup_method(self):
        """Setup temporary storage"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = StorageService(base_path=self.temp_dir)

    def teardown_method(self):
        """Cleanup"""
        shutil.rmtree(self.temp_dir)

    def test_multiple_storage_instances(self):
        """Test that multiple storage instances can access same job"""
        job = Job(id="test-job-9", url="https://youtube.com/test")

        # Save with first instance
        storage1 = StorageService(base_path=self.temp_dir)
        storage1.save_job_state(job)

        # Load with second instance
        storage2 = StorageService(base_path=self.temp_dir)
        loaded = storage2.load_job_state(job.id)

        assert loaded is not None
        assert loaded.id == job.id

    def test_artifact_checking_across_instances(self):
        """Test artifact checking works across storage instances"""
        job_id = "test-job-10"

        # Create artifact with first instance
        storage1 = StorageService(base_path=self.temp_dir)
        artifact_path = storage1.get_artifact_path(job_id, "test.txt")
        artifact_path.write_text("test data")

        # Check with second instance
        storage2 = StorageService(base_path=self.temp_dir)
        assert storage2.artifact_exists(job_id, "test.txt") is True


# Run tests with: pytest tests/test_idempotency.py -v
