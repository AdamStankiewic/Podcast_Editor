"""
Video Cache Service
Manages shared cache for downloaded YouTube videos to avoid re-downloading
"""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class VideoCacheService:
    """Manages video cache to avoid re-downloading same videos"""

    def __init__(self, cache_dir: str = "./data/_cache/videos"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, video_id: str) -> Path:
        """Get cache directory path for a video ID"""
        return self.cache_dir / video_id

    def get_cached_video(self, video_id: str) -> Optional[Path]:
        """
        Get cached video file if exists

        Args:
            video_id: YouTube video ID (e.g., "nlhDSfB9lCQ")

        Returns:
            Path to cached video file or None if not cached
        """
        cache_path = self.get_cache_path(video_id)
        video_file = cache_path / "video.mp4"

        if video_file.exists() and video_file.stat().st_size > 0:
            # Update access time
            self._update_metadata(video_id, "last_accessed")
            return video_file

        return None

    def get_cached_subtitles(self, video_id: str, lang: str = "de") -> Optional[Path]:
        """
        Get cached subtitle file if exists

        Args:
            video_id: YouTube video ID
            lang: Language code (default: "de")

        Returns:
            Path to cached subtitle file or None if not cached
        """
        cache_path = self.get_cache_path(video_id)
        sub_file = cache_path / f"subtitles_{lang}.vtt"

        if sub_file.exists():
            self._update_metadata(video_id, "last_accessed")
            return sub_file

        return None

    def cache_video(self, video_id: str, video_path: Path, url: str, metadata: Dict[str, Any] = None) -> Path:
        """
        Add video to cache

        Args:
            video_id: YouTube video ID
            video_path: Path to video file to cache
            url: Original YouTube URL
            metadata: Optional video metadata (title, duration, etc.)

        Returns:
            Path to cached video file
        """
        cache_path = self.get_cache_path(video_id)
        cache_path.mkdir(parents=True, exist_ok=True)

        # Copy video to cache
        cached_video = cache_path / "video.mp4"
        if not cached_video.exists():
            shutil.copy2(video_path, cached_video)

        # Save metadata
        meta = {
            "video_id": video_id,
            "url": url,
            "cached_at": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
            "file_size": cached_video.stat().st_size,
            "metadata": metadata or {}
        }
        self._save_metadata(video_id, meta)

        return cached_video

    def cache_subtitles(self, video_id: str, subtitles_path: Path, lang: str = "de") -> Path:
        """
        Add subtitles to cache

        Args:
            video_id: YouTube video ID
            subtitles_path: Path to subtitle file to cache
            lang: Language code

        Returns:
            Path to cached subtitle file
        """
        cache_path = self.get_cache_path(video_id)
        cache_path.mkdir(parents=True, exist_ok=True)

        # Copy subtitles to cache
        cached_subs = cache_path / f"subtitles_{lang}.vtt"
        if not cached_subs.exists():
            shutil.copy2(subtitles_path, cached_subs)

        # Update metadata
        self._update_metadata(video_id, "last_accessed")

        return cached_subs

    def is_cached(self, video_id: str) -> bool:
        """Check if video is in cache"""
        cache_path = self.get_cache_path(video_id)
        video_file = cache_path / "video.mp4"
        return video_file.exists() and video_file.stat().st_size > 0

    def get_cache_info(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get cache metadata for a video"""
        cache_path = self.get_cache_path(video_id)
        meta_file = cache_path / "metadata.json"

        if meta_file.exists():
            with meta_file.open("r", encoding="utf-8") as f:
                return json.load(f)

        return None

    def clear_cache(self, video_id: str):
        """Remove video from cache"""
        cache_path = self.get_cache_path(video_id)
        if cache_path.exists():
            shutil.rmtree(cache_path)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_size = 0
        video_count = 0

        for video_dir in self.cache_dir.iterdir():
            if video_dir.is_dir():
                video_count += 1
                for file in video_dir.glob("**/*"):
                    if file.is_file():
                        total_size += file.stat().st_size

        return {
            "video_count": video_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }

    def _save_metadata(self, video_id: str, metadata: Dict[str, Any]):
        """Save metadata for cached video"""
        cache_path = self.get_cache_path(video_id)
        meta_file = cache_path / "metadata.json"

        with meta_file.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _update_metadata(self, video_id: str, field: str, value: Any = None):
        """Update specific metadata field"""
        cache_path = self.get_cache_path(video_id)
        meta_file = cache_path / "metadata.json"

        if not meta_file.exists():
            return

        with meta_file.open("r", encoding="utf-8") as f:
            metadata = json.load(f)

        if field == "last_accessed":
            metadata[field] = datetime.now().isoformat()
        else:
            metadata[field] = value

        with meta_file.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)


# Singleton instance
_cache_service = None


def get_video_cache() -> VideoCacheService:
    """Get singleton video cache service instance"""
    global _cache_service
    if _cache_service is None:
        _cache_service = VideoCacheService()
    return _cache_service
