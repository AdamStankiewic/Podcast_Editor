"""
YouTube download service using yt-dlp
Handles video download and subtitle extraction
"""
import re
import subprocess
import sys
import shutil
import json
from pathlib import Path
from typing import Optional, Dict, Any


def _get_ytdlp_cmd():
    """Get yt-dlp command - prefer system binary, fallback to python -m."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


class YouTubeService:
    """Handles YouTube video downloads and metadata extraction"""

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize YouTube URL by ensuring it has a protocol

        Args:
            url: YouTube URL (may or may not have protocol)

        Returns:
            Normalized URL with https:// protocol
        """
        url = url.strip()

        # If URL doesn't start with http:// or https://, add https://
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'

        # Upgrade http:// to https://
        if url.startswith('http://'):
            url = url.replace('http://', 'https://', 1)

        return url

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """Extract video ID from YouTube URL"""
        # Normalize URL first
        url = YouTubeService.normalize_url(url)

        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/v\/([a-zA-Z0-9_-]{11})',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def get_video_info(url: str) -> Dict[str, Any]:
        """Get video metadata without downloading"""
        # Normalize URL first
        url = YouTubeService.normalize_url(url)

        try:
            result = subprocess.run(
                _get_ytdlp_cmd() + [
                    "--dump-json",
                    "--no-playlist",
                    url
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=180  # 3 minutes for slow connections or YouTube API delays
            )

            info = json.loads(result.stdout)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "description": info.get("description"),
                "uploader": info.get("uploader"),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get video info: {e}")

    @staticmethod
    def download_video(url: str, output_path: Path) -> Path:
        """
        Download video from YouTube
        Returns path to downloaded file
        """
        # Normalize URL first
        url = YouTubeService.normalize_url(url)

        try:
            # Download best quality video with audio
            result = subprocess.run(
                _get_ytdlp_cmd() + [
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "-o", str(output_path),
                    "--no-playlist",
                    "--retries", "10",
                    "--fragment-retries", "10",
                    "--socket-timeout", "30",
                    "--no-abort-on-unavailable-fragments",
                    url
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=3600  # 1 hour timeout for long videos
            )

            if not output_path.exists():
                raise RuntimeError(f"Download completed but file not found: {output_path}")

            return output_path

        except subprocess.TimeoutExpired:
            raise RuntimeError("Download timeout (>1 hour)")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"yt-dlp failed: {e.stderr}")
        except Exception as e:
            raise RuntimeError(f"Download error: {e}")

    @staticmethod
    def download_subtitles(url: str, output_path: Path, lang: str = "de") -> Optional[Path]:
        """
        Download German subtitles/transcript from YouTube
        Returns path to subtitle file or None if not available
        """
        # Normalize URL first
        url = YouTubeService.normalize_url(url)

        try:
            # Try to download auto-generated or manual subtitles
            result = subprocess.run(
                _get_ytdlp_cmd() + [
                    "--write-auto-sub",
                    "--write-sub",
                    "--sub-lang", lang,
                    "--skip-download",
                    "--sub-format", "vtt",
                    "-o", str(output_path.with_suffix("")),
                    url
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=180  # 3 minutes for slow connections or large subtitle files
            )

            # Look for generated subtitle files
            subtitle_patterns = [
                output_path.with_suffix(f".{lang}.vtt"),
                output_path.with_suffix(f".{lang}.auto.vtt"),
            ]

            for sub_file in subtitle_patterns:
                if sub_file.exists():
                    return sub_file

            return None

        except Exception as e:
            print(f"Subtitle download failed: {e}")
            return None

    @staticmethod
    def parse_vtt_to_text(vtt_path: Path) -> str:
        """
        Parse VTT subtitle file to plain text
        Removes timestamps, formatting, and consecutive duplicates

        YouTube auto-generated subtitles often have overlapping/duplicate lines
        that need to be deduplicated to avoid text bloat
        """
        if not vtt_path.exists():
            return ""

        with vtt_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        text_lines = []
        last_line = None

        for line in lines:
            line = line.strip()

            # Skip WEBVTT header
            if line.startswith("WEBVTT"):
                continue

            # Skip timestamps
            if "-->" in line:
                continue

            # Skip empty lines and numbers
            if not line or line.isdigit():
                continue

            # Remove HTML tags
            line = re.sub(r'<[^>]+>', '', line)

            # Skip if same as previous line (deduplication)
            if line and line != last_line:
                text_lines.append(line)
                last_line = line

        return "\n".join(text_lines)

    @staticmethod
    def get_video_duration_ffprobe(video_path: Path) -> float:
        """Get video duration using ffprobe"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                check=True
            )

            data = json.loads(result.stdout)
            return float(data["format"]["duration"])

        except Exception as e:
            raise RuntimeError(f"Failed to get video duration: {e}")
