"""
Celery configuration for background task processing
"""
import os
from celery import Celery
from dotenv import load_dotenv

# Load environment variables from .env file
# This is critical for local worker to access Azure credentials
load_dotenv()

# Get Redis URL from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Initialize Celery app
celery_app = Celery(
    "podcast_converter",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.workers.tasks"]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=14400,  # 4 hours max per task (enough for long podcasts with AI enhancement)
    task_soft_time_limit=12600,  # Soft limit warning at 3.5 hours
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=10,  # Restart worker after 10 tasks (prevent memory leaks)
)
