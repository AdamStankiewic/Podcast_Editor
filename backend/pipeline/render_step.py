"""
Pipeline Step 6: Render final video for target language
- Speed-adjust video to match audio length
- Mix TTS + background music with ducking
- Apply overlay PNG frame
- Export final MP4
Idempotent: Skips if final_{language}.mp4 already exists
"""
import os
from pathlib import Path
from backend.services.render import VideoRenderService
from backend.services.storage import get_storage


def render_final_video(
    job_id: str,
    target_language: str = "pl",
    overlay_path: str = "./assets/overlay.png",
    loop_audio_path: str = "./assets/loop.wav",
    enable_background_music: bool = False
) -> dict:
    """
    Render final video with target language narration

    Args:
        job_id: Job identifier
        target_language: Target language code (pl, fr, en)
        overlay_path: Path to overlay PNG
        loop_audio_path: Path to background music loop
        enable_background_music: Whether to add background music

    Returns:
        dict with final_video_path
    """
    storage = get_storage()

    # Language display names
    lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
    lang_name = lang_names.get(target_language, target_language.upper())

    original_video_path = storage.get_artifact_path(job_id, "original.mp4")

    # Use enhanced audio (from Resemble Enhance step), fallback to raw TTS
    enhanced_audio_path = storage.get_artifact_path(job_id, f"enhanced_{target_language}.wav")
    tts_audio_raw_path = storage.get_artifact_path(job_id, f"tts_{target_language}.wav")

    if enhanced_audio_path.exists():
        tts_audio_path = enhanced_audio_path
        storage.add_log(job_id, f"[{target_language.upper()}] Using enhanced audio for rendering", "INFO")
    elif tts_audio_raw_path.exists():
        tts_audio_path = tts_audio_raw_path
        storage.add_log(job_id, f"[{target_language.upper()}] Using raw TTS audio for rendering (enhancement not available)", "INFO")
    else:
        raise RuntimeError(f"{lang_name} audio not found. Run TTS and enhancement steps first.")

    final_video_path = storage.get_artifact_path(job_id, f"final_{target_language}.mp4")

    # Check if already rendered
    if storage.artifact_exists(job_id, f"final_{target_language}.mp4"):
        storage.add_log(job_id, f"[{target_language.upper()}] Final video already rendered, skipping", "INFO")
        return {"final_video_path": str(final_video_path)}

    # Check prerequisites
    if not original_video_path.exists():
        raise RuntimeError("Original video not found. Run download step first.")

    if not tts_audio_path.exists():
        raise RuntimeError("TTS audio not found. Run TTS step first.")

    storage.update_progress(job_id, "rendering", 6, message=f"Rendering {lang_name} video...")
    storage.add_log(job_id, f"[{target_language.upper()}] Starting video rendering pipeline...", "INFO")

    # Initialize render service with GPU support
    use_gpu = os.getenv("USE_GPU_ENCODING", "true").lower() == "true"
    render_service = VideoRenderService(
        overlay_path=overlay_path,
        loop_audio_path=loop_audio_path,
        use_gpu=use_gpu
    )

    def progress_callback(current, total, message):
        """Update progress during rendering"""
        storage.add_log(job_id, f"[{target_language.upper()}] [Render {current}/{total}] {message}", "INFO")

    try:
        render_service.render_final_video(
            original_video=original_video_path,
            tts_audio=tts_audio_path,
            output_video=final_video_path,
            progress_callback=progress_callback,
            enable_background_music=enable_background_music
        )

        storage.mark_step_complete(job_id, f"final_{target_language}", str(final_video_path))

        # Get file size
        size_mb = final_video_path.stat().st_size / (1024 * 1024)
        storage.add_log(job_id, f"[{target_language.upper()}] ✓ Final video rendered: {final_video_path.name} ({size_mb:.1f} MB)", "INFO")

        return {"final_video_path": str(final_video_path), "language": target_language}

    except Exception as e:
        storage.add_log(job_id, f"[{target_language.upper()}] ✗ Video rendering failed: {e}", "ERROR")
        raise RuntimeError(f"{lang_name} video rendering failed: {e}")
