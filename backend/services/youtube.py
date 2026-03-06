"""
YouTube download service using yt-dlp
Handles video download and subtitle extraction
"""
import os
import re
import subprocess
import sys
import shutil
import json
from pathlib import Path
from typing import Optional, Dict, Any, List


def _get_ytdlp_cmd():
    """Get yt-dlp command - prefer system binary, fallback to python -m."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def _get_cookie_args() -> List[str]:
    """Get cookie arguments for yt-dlp to help bypass YouTube SABR/403 restrictions.

    Set YTDLP_COOKIES_BROWSER env var (e.g. "chrome", "firefox", "brave")
    or YTDLP_COOKIES_FILE for a cookies.txt path.
    """
    cookies_browser = os.getenv("YTDLP_COOKIES_BROWSER", "")
    cookies_file = os.getenv("YTDLP_COOKIES_FILE", "")

    if cookies_browser:
        return ["--cookies-from-browser", cookies_browser]
    elif cookies_file and Path(cookies_file).exists():
        return ["--cookies", cookies_file]
    return []


def _run_ytdlp(args: List[str], timeout: int = 180, retry_with_cookies: bool = True) -> subprocess.CompletedProcess:
    """Run yt-dlp command with automatic retry using cookies on 403 errors.

    First tries without cookies. If it fails with a 403 error and cookies
    are configured, retries with cookies.
    """
    cmd = _get_ytdlp_cmd() + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout
        )
        return result
    except subprocess.CalledProcessError as e:
        is_403 = "403" in (e.stderr or "") or "403" in (e.stdout or "")
        cookie_args = _get_cookie_args()

        if is_403 and retry_with_cookies and cookie_args:
            # Retry with cookies
            cmd_with_cookies = _get_ytdlp_cmd() + cookie_args + args
            try:
                result = subprocess.run(
                    cmd_with_cookies,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=timeout
                )
                return result
            except subprocess.CalledProcessError:
                pass  # Fall through to raise original error

        raise


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
            result = _run_ytdlp(
                ["--dump-json", "--no-playlist", url],
                timeout=180
            )

            info = json.loads(result.stdout)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "description": info.get("description"),
                "uploader": info.get("uploader"),
            }
        except json.JSONDecodeError:
            raise RuntimeError(f"Failed to get video info: yt-dlp returned no valid output for URL: {url}. stderr: {result.stderr[:500] if result.stderr else 'empty'}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get video info: yt-dlp exited with error: {e.stderr[:500] if e.stderr else str(e)}")
        except Exception as e:
            raise RuntimeError(f"Failed to get video info: {e}")

    @staticmethod
    def download_video(url: str, output_path: Path) -> Path:
        """
        Download video from YouTube with multi-strategy fallback.

        Tries multiple approaches to handle YouTube SABR streaming restrictions:
        1. Best separate streams (highest quality)
        2. Best separate streams with missing_pot formats allowed
        3. Best combined format (lower quality but bypasses SABR)
        4. All above with cookies if configured

        Returns path to downloaded file
        """
        # Normalize URL first
        url = YouTubeService.normalize_url(url)

        base_args = [
            "--merge-output-format", "mp4",
            "-o", str(output_path),
            "--no-playlist",
            "--retries", "10",
            "--fragment-retries", "10",
            "--socket-timeout", "30",
            "--no-abort-on-unavailable-fragments",
        ]

        # Strategies ordered from best quality to most compatible
        strategies = [
            # Strategy 1: Best separate streams
            ["-f", "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"] + base_args + [url],
            # Strategy 2: Allow formats with missing POT (proof of origin token)
            ["-f", "bv*+ba/b", "--extractor-args", "youtube:formats=missing_pot"] + base_args + [url],
            # Strategy 3: Best single combined format (bypasses SABR completely)
            ["-f", "b[ext=mp4]/b"] + base_args + [url],
        ]

        last_error = None

        for i, strategy_args in enumerate(strategies):
            try:
                # Clean up partial download from previous attempt
                if output_path.exists():
                    output_path.unlink()

                _run_ytdlp(strategy_args, timeout=3600)

                if output_path.exists():
                    return output_path

            except subprocess.TimeoutExpired:
                raise RuntimeError("Download timeout (>1 hour)")
            except (subprocess.CalledProcessError, Exception) as e:
                last_error = e
                continue

        raise RuntimeError(f"All download strategies failed. Last error: {last_error}")

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
            _run_ytdlp(
                [
                    "--write-auto-sub",
                    "--write-sub",
                    "--sub-lang", lang,
                    "--skip-download",
                    "--sub-format", "vtt",
                    "-o", str(output_path.with_suffix("")),
                    url
                ],
                timeout=180
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
    def parse_vtt_with_timestamps(vtt_path: Path) -> list[dict]:
        """
        Parse VTT subtitle file preserving timestamps.
        Returns list of segments: [{"start": float, "end": float, "text": str}, ...]

        Merges overlapping/duplicate YouTube auto-sub entries into clean segments.
        """
        if not vtt_path.exists():
            return []

        def _vtt_time_to_seconds(time_str: str) -> float:
            """Convert VTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to seconds"""
            time_str = time_str.strip()
            parts = time_str.split(":")
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
            return 0.0

        with vtt_path.open("r", encoding="utf-8") as f:
            content = f.read()

        segments = []
        # Split into cue blocks (separated by blank lines)
        blocks = re.split(r'\n\s*\n', content)

        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue

            # Find timestamp line
            ts_line = None
            text_lines = []
            for line in lines:
                if "-->" in line:
                    ts_line = line
                elif ts_line is not None and line.strip():
                    # Skip cue identifiers (pure numbers or WEBVTT header)
                    if not line.strip().isdigit() and not line.strip().startswith("WEBVTT"):
                        text_lines.append(line.strip())

            if not ts_line or not text_lines:
                continue

            # Parse timestamps (ignore position tags after timestamp)
            ts_match = re.match(r'([\d:\.]+)\s*-->\s*([\d:\.]+)', ts_line)
            if not ts_match:
                continue

            start = _vtt_time_to_seconds(ts_match.group(1))
            end = _vtt_time_to_seconds(ts_match.group(2))

            # Clean text: remove HTML tags
            raw_text = " ".join(text_lines)
            clean_text = re.sub(r'<[^>]+>', '', raw_text).strip()

            if not clean_text:
                continue

            segments.append({"start": start, "end": end, "text": clean_text})

        # Merge: remove exact duplicate consecutive segments, merge overlaps
        merged = []
        for seg in segments:
            if not merged:
                merged.append(seg)
                continue

            prev = merged[-1]
            # Skip if identical text repeated immediately
            if seg["text"] == prev["text"]:
                # Extend end time if overlapping
                merged[-1]["end"] = max(prev["end"], seg["end"])
                continue

            # Extend previous segment if heavy overlap (>80% of new segment)
            overlap = max(0, prev["end"] - seg["start"])
            seg_duration = seg["end"] - seg["start"]
            if seg_duration > 0 and overlap / seg_duration > 0.8:
                # Append new text to previous
                merged[-1]["text"] = prev["text"].rstrip() + " " + seg["text"]
                merged[-1]["end"] = max(prev["end"], seg["end"])
                continue

            merged.append(dict(seg))

        return merged

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
