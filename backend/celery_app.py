"""
Celery app entry point
Imports celery app from workers.celery_config for easier CLI access
"""
from backend.workers.celery_config import celery_app

__all__ = ["celery_app"]
