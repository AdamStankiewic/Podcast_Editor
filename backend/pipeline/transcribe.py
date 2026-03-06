"""
Pipeline Step 2: Get German transcription
Priority: Download from YouTube, fallback to manual paste (UI)
Idempotent: Skips if transcript_de.txt already exists

Also saves transcript_de_timed.json (timestamped segments) for clip selection.
"""
import json
from pathlib import Path
from backend.services.youtube import YouTubeService
from backend.services.storage import get_storage


def get_transcript(job_id: str, url: str, manual_transcript: str = None) -> dict:
    """
    Get German transcript from YouTube or manual input

    Args:
        job_id: Job identifier
        url: YouTube URL
        manual_transcript: Optional manually pasted transcript

    Returns:
        dict with transcript_path, source ("youtube" or "manual")
    """
    storage = get_storage()
    yt_service = YouTubeService()

    transcript_path = storage.get_artifact_path(job_id, "transcript_de.txt")

    # Check if already exists
    if storage.artifact_exists(job_id, "transcript_de.txt"):
        storage.add_log(job_id, "Transcript already exists, skipping", "INFO")
        return {
            "transcript_path": str(transcript_path),
            "source": "cached"
        }

    storage.update_progress(job_id, "transcribing", 2, message="Getting German transcript...")

    # Try to download subtitles from YouTube
    try:
        storage.add_log(job_id, "Attempting to download German subtitles from YouTube...", "INFO")

        temp_path = storage.get_artifact_path(job_id, "temp_subtitle")
        subtitle_file = yt_service.download_subtitles(url, temp_path, lang="de")

        if subtitle_file and subtitle_file.exists():
            # Parse VTT to plain text
            transcript_text = yt_service.parse_vtt_to_text(subtitle_file)

            if transcript_text.strip():
                # Save plain transcript
                transcript_path.write_text(transcript_text, encoding="utf-8")

                # Save timestamped JSON for clip selection
                timed_segments = yt_service.parse_vtt_with_timestamps(subtitle_file)
                if timed_segments:
                    timed_path = storage.get_artifact_path(job_id, "transcript_de_timed.json")
                    timed_path.write_text(
                        json.dumps(timed_segments, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    storage.add_log(
                        job_id,
                        f"✓ Saved timed transcript ({len(timed_segments)} segments)",
                        "INFO"
                    )

                storage.mark_step_complete(job_id, "transcript_de", str(transcript_path))
                storage.add_log(job_id, f"✓ Downloaded transcript from YouTube ({len(transcript_text)} chars)", "INFO")

                # Cleanup temp subtitle
                subtitle_file.unlink()

                return {
                    "transcript_path": str(transcript_path),
                    "source": "youtube"
                }

    except Exception as e:
        storage.add_log(job_id, f"YouTube subtitle download failed: {e}", "WARNING")

    # Fallback: Use manual transcript if provided
    if manual_transcript and manual_transcript.strip():
        storage.add_log(job_id, "Using manually provided transcript", "INFO")

        transcript_path.write_text(manual_transcript.strip(), encoding="utf-8")
        storage.mark_step_complete(job_id, "transcript_de", str(transcript_path))

        storage.add_log(job_id, f"✓ Saved manual transcript ({len(manual_transcript)} chars)", "INFO")

        return {
            "transcript_path": str(transcript_path),
            "source": "manual"
        }

    # No transcript available
    error_msg = "No transcript available. YouTube subtitles not found and no manual transcript provided."
    storage.add_log(job_id, f"✗ {error_msg}", "ERROR")
    raise RuntimeError(error_msg)
