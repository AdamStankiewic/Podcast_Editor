"""
Celery tasks for podcast processing pipeline
"""
import os
from datetime import datetime
from backend.workers.celery_config import celery_app
from backend.models import Job, JobStatus
from backend.services.storage import get_storage
from backend.pipeline.download import download_video
from backend.pipeline.transcribe import get_transcript
from backend.pipeline.translate_step import translate_transcript
from backend.pipeline.tts_step import generate_tts
from backend.pipeline.render_step import render_final_video


@celery_app.task(bind=True, name="process_podcast")
def process_podcast_task(self, job_id: str, url: str, manual_transcript: str = None):
    """
    Main pipeline task - processes entire podcast conversion

    Args:
        job_id: Unique job identifier
        url: YouTube URL
        manual_transcript: Optional manual German transcript
    """
    storage = get_storage()

    # Load or create job
    job = storage.load_job_state(job_id)
    if not job:
        storage.add_log(job_id, "Job not found, cannot process", "ERROR")
        return {"error": "Job not found"}

    try:
        # Update status
        job.status = JobStatus.DOWNLOADING
        storage.save_job_state(job)

        # STEP 1: Download video
        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 1: Downloading video from YouTube", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        download_result = download_video(job_id, url)

        # Update job metadata
        job.video_id = download_result.get("video_id")
        job.video_title = download_result.get("title")
        job.video_duration = download_result.get("duration")
        storage.save_job_state(job)

        # STEP 2: Get transcript
        job.status = JobStatus.TRANSCRIBING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 2: Getting German transcript", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        transcript_result = get_transcript(job_id, url, manual_transcript)

        # STEP 3: Translate
        job.status = JobStatus.TRANSLATING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 3: Translating to Polish", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        openai_key = os.getenv("OPENAI_API_KEY")
        translate_result = translate_transcript(job_id, openai_api_key=openai_key)

        # STEP 4: Generate TTS
        job.status = JobStatus.GENERATING_TTS
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 4: Generating TTS audio", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        tts_result = generate_tts(
            job_id=job_id,
            speech_key=os.getenv("SPEECH_KEY"),
            speech_region=os.getenv("SPEECH_REGION"),
            voice=os.getenv("TTS_VOICE", "en-GB-Ollie:DragonHDLatestNeural"),
            rate=os.getenv("TTS_RATE", "-8%"),
            pitch=os.getenv("TTS_PITCH", "0%"),
            pronunciations_csv=os.getenv("PRONUNCIATIONS_CSV", "./pronunciations.csv")
        )

        # STEP 5: Render final video
        job.status = JobStatus.RENDERING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 5: Rendering final video", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        render_result = render_final_video(
            job_id=job_id,
            overlay_path=os.getenv("OVERLAY_PATH", "./assets/overlay.png"),
            loop_audio_path=os.getenv("LOOP_AUDIO_PATH", "./assets/loop.wav"),
            enable_background_music=job.enable_background_music
        )

        # DONE
        job.status = JobStatus.DONE
        job.completed_at = datetime.utcnow()
        storage.update_progress(job_id, "done", 7, message="Processing complete!")
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "✅ PIPELINE COMPLETE!", "INFO")
        storage.add_log(job_id, f"Final video: {render_result['final_video_path']}", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        return {
            "status": "success",
            "job_id": job_id,
            "final_video": render_result["final_video_path"]
        }

    except Exception as e:
        # Handle error
        job.status = JobStatus.ERROR
        job.error_message = str(e)
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "ERROR")
        storage.add_log(job_id, f"❌ PIPELINE FAILED: {e}", "ERROR")
        storage.add_log(job_id, "=" * 60, "ERROR")

        return {
            "status": "error",
            "job_id": job_id,
            "error": str(e)
        }
