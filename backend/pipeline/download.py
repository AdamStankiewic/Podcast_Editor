"""
Pipeline Step 1: Download video from YouTube
Idempotent: Skips if original.mp4 already exists
"""
import os
from pathlib import Path
from backend.services.youtube import YouTubeService
from backend.services.storage import get_storage


def download_video(job_id: str, url: str) -> dict:
    """
    Download video from YouTube

    Returns:
        dict with video_id, title, duration, video_path
    """
    storage = get_storage()
    yt_service = YouTubeService()

    # Check if already downloaded
    video_path = storage.get_artifact_path(job_id, "original.mp4")

    if storage.artifact_exists(job_id, "original.mp4"):
        storage.add_log(job_id, "Video already downloaded, skipping", "INFO")

        # Still need to get metadata
        try:
            info = yt_service.get_video_info(url)
            return {
                "video_id": info["id"],
                "title": info["title"],
                "duration": info["duration"],
                "video_path": str(video_path)
            }
        except:
            # Fallback if metadata fetch fails
            return {
                "video_id": yt_service.extract_video_id(url),
                "video_path": str(video_path)
            }

    # Download video
    storage.add_log(job_id, f"Downloading video from {url}...", "INFO")
    storage.update_progress(job_id, "downloading", 1, message="Downloading video...")

    try:
        # Get metadata first
        info = yt_service.get_video_info(url)

        # Check duration limit (configurable via .env)
        max_hours = int(os.getenv("MAX_VIDEO_DURATION_HOURS", "2"))
        max_duration = max_hours * 3600  # Convert hours to seconds

        if info.get("duration", 0) > max_duration:
            raise ValueError(f"Video duration ({info['duration']}s) exceeds {max_hours} hour limit")

        # Download
        downloaded_path = yt_service.download_video(url, video_path)

        storage.mark_step_complete(job_id, "original_video", str(downloaded_path))
        storage.add_log(job_id, f"✓ Downloaded: {info['title']}", "INFO")

        return {
            "video_id": info["id"],
            "title": info["title"],
            "duration": info["duration"],
            "video_path": str(downloaded_path)
        }

    except Exception as e:
        storage.add_log(job_id, f"✗ Download failed: {e}", "ERROR")
        raise RuntimeError(f"Video download failed: {e}")
