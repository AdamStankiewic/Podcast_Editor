"""
Pipeline Step 5: Render final video
- Speed-adjust video to match audio length
- Mix TTS + background music with ducking
- Apply overlay PNG frame
- Export final MP4
Idempotent: Skips if final.mp4 already exists
"""
import os
from pathlib import Path
from backend.services.render import VideoRenderService
from backend.services.storage import get_storage


def render_final_video(
    job_id: str,
    overlay_path: str = "./assets/overlay.png",
    loop_audio_path: str = "./assets/loop.wav"
) -> dict:
    """
    Render final video with Polish narration

    Returns:
        dict with final_video_path
    """
    storage = get_storage()

    original_video_path = storage.get_artifact_path(job_id, "original.mp4")
    tts_audio_path = storage.get_artifact_path(job_id, "tts.wav")
    final_video_path = storage.get_artifact_path(job_id, "final.mp4")

    # Check if already rendered
    if storage.artifact_exists(job_id, "final.mp4"):
        storage.add_log(job_id, "Final video already rendered, skipping", "INFO")
        return {"final_video_path": str(final_video_path)}

    # Check prerequisites
    if not original_video_path.exists():
        raise RuntimeError("Original video not found. Run download step first.")

    if not tts_audio_path.exists():
        raise RuntimeError("TTS audio not found. Run TTS step first.")

    storage.update_progress(job_id, "rendering", 5, message="Rendering final video...")
    storage.add_log(job_id, "Starting video rendering pipeline...", "INFO")

    # Initialize render service with GPU support
    use_gpu = os.getenv("USE_GPU_ENCODING", "true").lower() == "true"
    render_service = VideoRenderService(
        overlay_path=overlay_path,
        loop_audio_path=loop_audio_path,
        use_gpu=use_gpu
    )

    def progress_callback(current, total, message):
        """Update progress during rendering"""
        storage.add_log(job_id, f"[Render {current}/{total}] {message}", "INFO")

    try:
        render_service.render_final_video(
            original_video=original_video_path,
            tts_audio=tts_audio_path,
            output_video=final_video_path,
            progress_callback=progress_callback
        )

        storage.mark_step_complete(job_id, "final_video", str(final_video_path))

        # Get file size
        size_mb = final_video_path.stat().st_size / (1024 * 1024)
        storage.add_log(job_id, f"✓ Final video rendered: {final_video_path.name} ({size_mb:.1f} MB)", "INFO")

        return {"final_video_path": str(final_video_path)}

    except Exception as e:
        storage.add_log(job_id, f"✗ Video rendering failed: {e}", "ERROR")
        raise RuntimeError(f"Video rendering failed: {e}")
