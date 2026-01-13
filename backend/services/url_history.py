"""
URL History Service
Tracks which YouTube URLs have been processed to avoid duplicates
"""
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime


class URLHistoryService:
    """Tracks processed YouTube URLs"""

    def __init__(self, history_file: str = "./data/_history/processed_urls.json"):
        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize history file if doesn't exist
        if not self.history_file.exists():
            self._save_history({})

    def _load_history(self) -> Dict[str, Any]:
        """Load history from JSON file"""
        try:
            with self.history_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_history(self, history: Dict[str, Any]):
        """Save history to JSON file"""
        with self.history_file.open("w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def is_url_processed(self, url: str) -> bool:
        """Check if URL has been processed before"""
        history = self._load_history()
        normalized_url = self._normalize_url(url)
        return normalized_url in history

    def get_url_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get processing history for a URL

        Returns:
            Dict with job_ids, video_id, first_processed, last_processed, process_count
            or None if URL not found
        """
        history = self._load_history()
        normalized_url = self._normalize_url(url)
        return history.get(normalized_url)

    def add_url(self, url: str, job_id: str, video_id: str, metadata: Dict[str, Any] = None):
        """
        Add URL to history or update if exists

        Args:
            url: YouTube URL
            job_id: Job ID that processed this URL
            video_id: YouTube video ID
            metadata: Optional video metadata (title, duration, etc.)
        """
        history = self._load_history()
        normalized_url = self._normalize_url(url)

        if normalized_url in history:
            # Update existing entry
            entry = history[normalized_url]
            entry["job_ids"].append(job_id)
            entry["last_processed"] = datetime.now().isoformat()
            entry["process_count"] += 1
        else:
            # Create new entry
            entry = {
                "url": url,
                "video_id": video_id,
                "job_ids": [job_id],
                "first_processed": datetime.now().isoformat(),
                "last_processed": datetime.now().isoformat(),
                "process_count": 1,
                "metadata": metadata or {}
            }
            history[normalized_url] = entry

        self._save_history(history)

    def get_all_urls(self) -> List[Dict[str, Any]]:
        """Get all processed URLs sorted by last processed (newest first)"""
        history = self._load_history()
        urls = list(history.values())
        urls.sort(key=lambda x: x["last_processed"], reverse=True)
        return urls

    def get_duplicate_jobs(self, url: str) -> List[str]:
        """Get list of job IDs that processed this URL"""
        info = self.get_url_info(url)
        return info["job_ids"] if info else []

    def get_stats(self) -> Dict[str, Any]:
        """Get history statistics"""
        history = self._load_history()
        total_urls = len(history)
        total_jobs = sum(entry["process_count"] for entry in history.values())
        duplicates = sum(1 for entry in history.values() if entry["process_count"] > 1)

        return {
            "total_unique_urls": total_urls,
            "total_jobs": total_jobs,
            "duplicate_urls": duplicates,
            "average_jobs_per_url": round(total_jobs / total_urls, 2) if total_urls > 0 else 0
        }

    def clear_history(self):
        """Clear all history"""
        self._save_history({})

    def remove_url(self, url: str):
        """Remove URL from history"""
        history = self._load_history()
        normalized_url = self._normalize_url(url)
        if normalized_url in history:
            del history[normalized_url]
            self._save_history(history)

    def _normalize_url(self, url: str) -> str:
        """
        Normalize YouTube URL to canonical form
        Handles different URL formats (youtube.com/watch, youtu.be, etc.)
        """
        # Remove query parameters except 'v'
        # Remove timestamp fragments
        url = url.split("#")[0]  # Remove fragment
        url = url.split("&t=")[0]  # Remove timestamp

        # Extract video ID and create canonical URL
        from backend.services.youtube import YouTubeService
        video_id = YouTubeService.extract_video_id(url)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

        # Fallback: return original URL
        return url


# Singleton instance
_history_service = None


def get_url_history() -> URLHistoryService:
    """Get singleton URL history service instance"""
    global _history_service
    if _history_service is None:
        _history_service = URLHistoryService()
    return _history_service
