"""
Pipeline Step 1: Download video from YouTube
Uses video cache to avoid re-downloading same videos
Idempotent: Skips if original.mp4 already exists
"""
import os
import shutil
from pathlib import Path
from backend.services.youtube import YouTubeService
from backend.services.storage import get_storage
from backend.services.video_cache import get_video_cache
from backend.services.url_history import get_url_history


def download_video(job_id: str, url: str) -> dict:
    """
    Download video from YouTube (with caching)

    Returns:
        dict with video_id, title, duration, video_path, from_cache
    """
    storage = get_storage()
    yt_service = YouTubeService()
    cache = get_video_cache()
    history = get_url_history()

    # Check if already downloaded for THIS job
    video_path = storage.get_artifact_path(job_id, "original.mp4")

    if storage.artifact_exists(job_id, "original.mp4"):
        storage.add_log(job_id, "Video already downloaded for this job, skipping", "INFO")

        # Still need to get metadata
        try:
            info = yt_service.get_video_info(url)
            video_id = info["id"]

            # Add to history
            history.add_url(url, job_id, video_id, {
                "title": info["title"],
                "duration": info["duration"]
            })

            return {
                "video_id": video_id,
                "title": info["title"],
                "duration": info["duration"],
                "video_path": str(video_path),
                "from_cache": False
            }
        except:
            # Fallback if metadata fetch fails
            video_id = yt_service.extract_video_id(url)
            return {
                "video_id": video_id,
                "video_path": str(video_path),
                "from_cache": False
            }

    # Get video ID
    video_id = yt_service.extract_video_id(url)
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")

    # Check if URL was processed before
    if history.is_url_processed(url):
        url_info = history.get_url_info(url)
        previous_jobs = url_info["job_ids"]
        storage.add_log(
            job_id,
            f"⚠ This URL was already processed in {len(previous_jobs)} job(s): {', '.join(previous_jobs[-3:])}",
            "WARNING"
        )

    # Check cache first
    cached_video = cache.get_cached_video(video_id)
    if cached_video:
        storage.add_log(job_id, f"✓ Found video in cache (video_id: {video_id})", "INFO")
        storage.add_log(job_id, f"Copying from cache instead of downloading...", "INFO")

        # Copy from cache to job directory
        shutil.copy2(cached_video, video_path)
        storage.mark_step_complete(job_id, "original_video", str(video_path))

        # Get cache metadata
        cache_info = cache.get_cache_info(video_id)
        metadata = cache_info.get("metadata", {})

        # Add to history
        history.add_url(url, job_id, video_id, metadata)

        storage.add_log(job_id, f"✓ Video copied from cache", "INFO")

        return {
            "video_id": video_id,
            "title": metadata.get("title", "Unknown"),
            "duration": metadata.get("duration", 0),
            "video_path": str(video_path),
            "from_cache": True
        }

    # Download video (not in cache)
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

        # Add to cache
        storage.add_log(job_id, f"Adding video to cache (video_id: {video_id})...", "INFO")
        cache.cache_video(video_id, downloaded_path, url, {
            "title": info["title"],
            "duration": info["duration"],
            "uploader": info.get("uploader", "Unknown")
        })

        # Add to history
        history.add_url(url, job_id, video_id, {
            "title": info["title"],
            "duration": info["duration"]
        })

        storage.mark_step_complete(job_id, "original_video", str(downloaded_path))
        storage.add_log(job_id, f"✓ Downloaded and cached: {info['title']}", "INFO")

        return {
            "video_id": video_id,
            "title": info["title"],
            "duration": info["duration"],
            "video_path": str(downloaded_path),
            "from_cache": False
        }

    except Exception as e:
        storage.add_log(job_id, f"✗ Download failed: {e}", "ERROR")
        raise RuntimeError(f"Video download failed: {e}")

