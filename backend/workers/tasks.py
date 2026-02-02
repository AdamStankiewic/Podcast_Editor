"""
Celery tasks for podcast processing pipeline with multi-language support
New architecture: Separate tasks per language with dynamic time limits
"""
import gc
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.workers.celery_config import celery_app
from backend.models import Job, JobStatus
from backend.services.storage import get_storage
from backend.pipeline.download import download_video
from backend.pipeline.transcribe import get_transcript
from backend.pipeline.translate_step import translate_transcript
from backend.pipeline.tts_step import generate_tts
from backend.pipeline.enhance_step import enhance_audio
from backend.pipeline.render_step import render_final_video


def _cleanup_gpu_memory():
    """Free GPU memory and Python objects after processing.

    Unloads Resemble Enhance models, DeepFilterNet, and forces
    garbage collection + CUDA cache clear to prevent memory leaks
    across jobs.
    """
    try:
        import torch

        # Reset audio postprocessing singleton (holds Resemble Enhance state)
        from backend.services import audio_postprocessing
        audio_postprocessing._audio_postprocessing_service = None

        # Force garbage collection
        gc.collect()

        # Clear CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            allocated = torch.cuda.memory_allocated() / 1024**3
            reserved = torch.cuda.memory_reserved() / 1024**3
            print(f"GPU memory after cleanup: {allocated:.1f} GB allocated, {reserved:.1f} GB reserved")

    except Exception as e:
        print(f"Warning: GPU cleanup failed: {e}")


def calculate_orchestrator_limits(video_duration: float, num_languages: int) -> dict:
    """
    Calculate dynamic time limits for process_podcast orchestrator task

    The orchestrator runs languages SEQUENTIALLY to avoid GPU overload, so total time is:
    - Download + Transcribe: ~30 min (fixed overhead)
    - Per language: calculated by calculate_language_task_limits()
    - Total: download_time + (num_languages * per_language_time)

    Args:
        video_duration: Video duration in seconds
        num_languages: Number of languages to process

    Returns:
        dict with soft_limit and hard_limit in seconds

    Examples:
        84 min video, 3 languages: 30min + 3 × 2.4h = 7.7h
        60 min video, 2 languages: 30min + 2 × 2.4h = 5.3h
    """
    # Download + Transcribe overhead (in seconds)
    download_transcribe_time = 1800  # 30 minutes

    # Per-language time (using same calculation as language task)
    lang_limits = calculate_language_task_limits(video_duration)
    per_language_time = lang_limits['estimated_time']

    # Total time for orchestrator
    total_time = download_transcribe_time + (num_languages * per_language_time)

    # Add safety margins
    soft_limit = int(total_time * 1.1)  # 10% margin
    hard_limit = int(total_time * 1.2)  # 20% margin

    return {
        'soft_limit': soft_limit,
        'hard_limit': hard_limit,
        'estimated_time': int(total_time)
    }


def calculate_language_task_limits(video_duration: float) -> dict:
    """
    Calculate dynamic time limits for language processing task based on video duration

    Time breakdown per language:
    - Translation + TTS: ~40 min (fixed overhead)
    - Enhance (Resemble): video_duration * 0.25 (max 40 min for very long videos)
    - Render (FFmpeg NVENC): video_duration * 1.5 (3.4x realtime = 0.44x duration)

    Args:
        video_duration: Video duration in seconds

    Returns:
        dict with soft_limit and hard_limit in seconds

    Examples:
        10 min video: 40 + 2.5 + 15 = 58 min
        1h video: 40 + 15 + 90 = 145 min (2.4h)
        2h video: 40 + 30 + 180 = 250 min (4.2h)
    """
    # Fixed overhead for translation + TTS (in seconds)
    base_time = 2400  # 40 minutes

    # AI enhancement time (Resemble Enhance on GPU)
    # Typically 0.15-0.25x video duration, capped at 40 min
    enhance_time = min(video_duration * 0.25, 2400)

    # Video rendering time (FFmpeg NVENC)
    # Observed: ~3.4x realtime speed = 0.44x duration (conservative: 1.5x)
    render_time = video_duration * 1.5

    # Total time for one language
    total_time = base_time + enhance_time + render_time

    # Add 10% safety margin for soft limit
    soft_limit = int(total_time * 1.1)

    # Hard limit: 20% margin
    hard_limit = int(total_time * 1.2)

    return {
        'soft_limit': soft_limit,
        'hard_limit': hard_limit,
        'estimated_time': int(total_time)
    }


@celery_app.task(bind=True, name="process_language")
def process_language_task(self, job_id: str, language: str, video_duration: float):
    """
    Process a single language: Translation → TTS → Enhance → Render

    This task has DYNAMIC time limits based on video duration.
    GPU-intensive operations (Enhance, Render) are isolated per language.

    Args:
        job_id: Job identifier
        language: Target language code (pl, fr, en)
        video_duration: Video duration in seconds (for limit calculation)

    Returns:
        dict with status, language, and final_video_path or error
    """
    storage = get_storage()

    # Calculate and log time limits
    limits = calculate_language_task_limits(video_duration)
    storage.add_log(
        job_id,
        f"[{language.upper()}] Task limits: {limits['estimated_time']//60} min estimated, "
        f"{limits['soft_limit']//60} min soft, {limits['hard_limit']//60} min hard",
        "INFO"
    )

    # Override task time limits dynamically
    self.time_limit = limits['hard_limit']
    self.soft_time_limit = limits['soft_limit']

    try:
        # Language display name
        lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
        lang_name = lang_names.get(language, language.upper())

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"🔷 Processing {lang_name} ({language.upper()})", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        # STEP 1: Translation
        storage.add_log(job_id, f"[{language.upper()}] Step 1/4: Translating to {lang_name}...", "INFO")
        translate_result = translate_transcript(
            job_id=job_id,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            target_language=language
        )
        storage.add_log(job_id, f"[{language.upper()}] ✓ Translation complete", "INFO")

        # STEP 2: TTS Generation (Chatterbox primary, Azure fallback)
        storage.add_log(job_id, f"[{language.upper()}] Step 2/4: Generating TTS audio...", "INFO")
        tts_result = generate_tts(
            job_id=job_id,
            target_language=language,
            pronunciations_csv=os.getenv("PRONUNCIATIONS_CSV", "./pronunciations.csv"),
            # Provider is auto-selected from TTS_PROVIDER env var (default: chatterbox)
            # Chatterbox params loaded from CHATTERBOX_* env vars
            # Azure fallback params loaded from SPEECH_KEY, TTS_VOICE, etc.
        )
        provider_used = tts_result.get("provider", "unknown")
        storage.add_log(job_id, f"[{language.upper()}] ✓ TTS complete (provider: {provider_used})", "INFO")

        # STEP 3: Audio Enhancement (GPU - Resemble Enhance)
        storage.add_log(job_id, f"[{language.upper()}] Step 3/4: Enhancing audio (GPU)...", "INFO")
        enhance_result = enhance_audio(
            job_id=job_id,
            target_language=language
        )
        storage.add_log(job_id, f"[{language.upper()}] ✓ Audio enhancement complete", "INFO")

        # STEP 4: Video Rendering (GPU - NVENC)
        storage.add_log(job_id, f"[{language.upper()}] Step 4/4: Rendering final video (GPU)...", "INFO")
        render_result = render_final_video(
            job_id=job_id,
            target_language=language,
            overlay_path=os.getenv("OVERLAY_PATH", "./assets/overlay.png"),
            loop_audio_path=os.getenv("LOOP_AUDIO_PATH", "./assets/loop.wav"),
            enable_background_music=storage.load_job_state(job_id).enable_background_music
        )
        storage.add_log(job_id, f"[{language.upper()}] ✓ Video rendering complete", "INFO")

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"✅ {lang_name} processing COMPLETE!", "INFO")
        storage.add_log(job_id, f"   Output: {render_result['final_video_path']}", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        return {
            "status": "success",
            "language": language,
            "final_video_path": render_result["final_video_path"]
        }

    except Exception as e:
        # Log error but don't crash - allow other languages to continue
        storage.add_log(job_id, "=" * 60, "ERROR")
        storage.add_log(job_id, f"❌ {lang_name} processing FAILED: {e}", "ERROR")
        storage.add_log(job_id, "=" * 60, "ERROR")

        return {
            "status": "error",
            "language": language,
            "error": str(e)
        }

    finally:
        # Always free GPU/RAM after each language to prevent memory leaks
        _cleanup_gpu_memory()
        storage.add_log(job_id, f"[{language.upper()}] GPU memory released", "INFO")


@celery_app.task(bind=True, name="process_podcast")
def process_podcast_task(self, job_id: str, url: str, manual_transcript: str = None):
    """
    Main orchestrator task - coordinates multi-language podcast conversion

    New architecture (SAFE for GPU):
    1. Download + Transcribe (shared, 1x)
    2. Spawn sequential language tasks (PL → FR → EN)
       - Each language task handles: Translate → TTS → Enhance → Render
       - Sequential execution prevents GPU overload
       - Dynamic time limits per task based on video duration

    Supports PARTIAL SUCCESS: If some languages fail, others continue

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
        # Get languages from job
        languages = job.languages if job.languages else ["pl"]
        lang_display = ", ".join([lang.upper() for lang in languages])

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"🌍 Multi-language pipeline: {lang_display}", "INFO")
        storage.add_log(job_id, f"🔧 New architecture: Sequential language tasks with dynamic limits", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        # PHASE 1: Download video (shared for all languages)
        job.status = JobStatus.DOWNLOADING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "PHASE 1/3: Downloading video from YouTube", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        download_result = download_video(job_id, url)

        # Update job metadata
        job.video_id = download_result.get("video_id")
        job.video_title = download_result.get("title")
        job.video_duration = download_result.get("duration")
        storage.save_job_state(job)

        video_duration = job.video_duration or 600  # Default 10 min if unknown

        storage.add_log(
            job_id,
            f"✓ Video downloaded: {job.video_title} ({video_duration/60:.1f} minutes)",
            "INFO"
        )

        # Set dynamic time limits for orchestrator based on video duration and language count
        orchestrator_limits = calculate_orchestrator_limits(video_duration, len(languages))
        storage.add_log(
            job_id,
            f"⏱️  Orchestrator time limits: {orchestrator_limits['estimated_time']//60} min estimated, "
            f"{orchestrator_limits['soft_limit']//60} min soft, {orchestrator_limits['hard_limit']//60} min hard",
            "INFO"
        )

        # Override task time limits dynamically
        self.time_limit = orchestrator_limits['hard_limit']
        self.soft_time_limit = orchestrator_limits['soft_limit']

        # PHASE 2: Get transcript (shared for all languages)
        job.status = JobStatus.TRANSCRIBING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "PHASE 2/3: Getting German transcript", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        transcript_result = get_transcript(job_id, url, manual_transcript)

        storage.add_log(job_id, "✓ Transcript acquired", "INFO")

        # PHASE 3: Process each language SEQUENTIALLY (to avoid GPU overload)
        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"PHASE 3/3: Processing {len(languages)} languages SEQUENTIALLY", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        final_videos = {}
        language_errors = {}

        for idx, lang in enumerate(languages, 1):
            storage.add_log(
                job_id,
                f"▶ Starting language {idx}/{len(languages)}: {lang.upper()}",
                "INFO"
            )

            # Update job status to reflect current language being processed
            if idx == 1:
                job.status = JobStatus.TRANSLATING
            elif idx <= len(languages) / 2:
                job.status = JobStatus.GENERATING_TTS
            else:
                job.status = JobStatus.RENDERING
            storage.save_job_state(job)

            try:
                # Call language-specific task (runs synchronously)
                result = process_language_task(job_id, lang, video_duration)

                if result["status"] == "success":
                    final_videos[lang] = result["final_video_path"]
                    storage.add_log(
                        job_id,
                        f"✅ {lang.upper()} completed successfully ({idx}/{len(languages)})",
                        "INFO"
                    )
                else:
                    # Language task returned error but didn't crash
                    language_errors[lang] = result.get("error", "Unknown error")
                    storage.add_log(
                        job_id,
                        f"⚠ {lang.upper()} failed but continuing with other languages",
                        "WARNING"
                    )

            except Exception as e:
                # Unexpected error in language task
                language_errors[lang] = str(e)
                storage.add_log(
                    job_id,
                    f"❌ {lang.upper()} crashed: {e}, continuing with other languages",
                    "ERROR"
                )

        # FINAL STATUS DETERMINATION
        job.completed_at = datetime.utcnow()

        if language_errors and final_videos:
            # PARTIAL SUCCESS: Some languages succeeded, some failed
            job.status = JobStatus.PARTIAL_SUCCESS
            job.language_errors = language_errors

            success_langs = ", ".join([lang.upper() for lang in final_videos.keys()])
            failed_langs = ", ".join([lang.upper() for lang in language_errors.keys()])

            job.error_message = f"Partial success: {success_langs} completed, {failed_langs} failed"

            storage.add_log(job_id, "=" * 60, "WARNING")
            storage.add_log(job_id, "⚠️  PARTIAL SUCCESS", "WARNING")
            storage.add_log(job_id, f"✅ Succeeded: {success_langs}", "INFO")
            storage.add_log(job_id, f"❌ Failed: {failed_langs}", "ERROR")
            for lang, error in language_errors.items():
                storage.add_log(job_id, f"   [{lang.upper()}] {error}", "ERROR")
            storage.add_log(job_id, "=" * 60, "WARNING")

        elif not final_videos:
            # ALL FAILED
            job.status = JobStatus.ERROR
            job.language_errors = language_errors
            job.error_message = "All languages failed"

            storage.add_log(job_id, "=" * 60, "ERROR")
            storage.add_log(job_id, "❌ ALL LANGUAGES FAILED", "ERROR")
            for lang, error in language_errors.items():
                storage.add_log(job_id, f"   [{lang.upper()}] {error}", "ERROR")
            storage.add_log(job_id, "=" * 60, "ERROR")

        else:
            # ALL SUCCEEDED
            job.status = JobStatus.DONE

            storage.add_log(job_id, "=" * 60, "INFO")
            storage.add_log(job_id, "✅ ALL LANGUAGES COMPLETED SUCCESSFULLY!", "INFO")
            for lang, video_path in final_videos.items():
                storage.add_log(job_id, f"   [{lang.upper()}] {video_path}", "INFO")
            storage.add_log(job_id, "=" * 60, "INFO")

        storage.save_job_state(job)
        storage.update_progress(job_id, "done", 6, message=f"Processing complete: {job.status}")

        return {
            "status": job.status.value if hasattr(job.status, 'value') else str(job.status),
            "job_id": job_id,
            "final_videos": final_videos,
            "errors": language_errors
        }

    except Exception as e:
        # Catastrophic failure in orchestrator (download/transcript phase)
        job.status = JobStatus.ERROR
        job.error_message = str(e)
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "ERROR")
        storage.add_log(job_id, f"❌ PIPELINE FAILED (orchestrator): {e}", "ERROR")
        storage.add_log(job_id, "=" * 60, "ERROR")

        return {
            "status": "error",
            "job_id": job_id,
            "error": str(e)
        }
