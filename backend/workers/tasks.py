"""
Celery tasks for podcast processing pipeline with multi-language support
"""
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


@celery_app.task(bind=True, name="process_podcast")
def process_podcast_task(self, job_id: str, url: str, manual_transcript: str = None):
    """
    Main pipeline task - processes entire podcast conversion with multi-language support

    Pipeline architecture (SAFE mode):
    1. Download + Transcribe (1x shared)
    2. Translation (parallel for all languages)
    3. TTS (parallel for all languages)
    4. Resemble Enhance (sequential: PL→EN→FR to avoid GPU overload)
    5. Rendering (sequential: PL→EN→FR to avoid CPU/GPU overload)

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
        storage.add_log(job_id, "=" * 60, "INFO")

        # STEP 1: Download video (shared)
        job.status = JobStatus.DOWNLOADING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 1/6: Downloading video from YouTube", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        download_result = download_video(job_id, url)

        # Update job metadata
        job.video_id = download_result.get("video_id")
        job.video_title = download_result.get("title")
        job.video_duration = download_result.get("duration")
        storage.save_job_state(job)

        # STEP 2: Get transcript (shared)
        job.status = JobStatus.TRANSCRIBING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "STEP 2/6: Getting German transcript", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        transcript_result = get_transcript(job_id, url, manual_transcript)

        # STEP 3: Translate (PARALLEL for all languages)
        job.status = JobStatus.TRANSLATING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"STEP 3/6: Translating to {lang_display} (PARALLEL)", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        openai_key = os.getenv("OPENAI_API_KEY")

        def translate_language(lang):
            """Translate to a single language"""
            return translate_transcript(job_id, openai_api_key=openai_key, target_language=lang)

        # Run translations in parallel
        with ThreadPoolExecutor(max_workers=len(languages)) as executor:
            future_to_lang = {executor.submit(translate_language, lang): lang for lang in languages}
            for future in as_completed(future_to_lang):
                lang = future_to_lang[future]
                try:
                    result = future.result()
                    storage.add_log(job_id, f"✓ {lang.upper()} translation complete", "INFO")
                except Exception as e:
                    storage.add_log(job_id, f"✗ {lang.upper()} translation failed: {e}", "ERROR")
                    raise

        # STEP 4: Generate TTS (PARALLEL for all languages)
        job.status = JobStatus.GENERATING_TTS
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"STEP 4/6: Generating TTS for {lang_display} (PARALLEL)", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        def generate_tts_language(lang):
            """Generate TTS for a single language"""
            return generate_tts(
                job_id=job_id,
                speech_key=os.getenv("SPEECH_KEY"),
                speech_region=os.getenv("SPEECH_REGION"),
                voice=os.getenv("TTS_VOICE", "en-GB-OllieMultilingualNeural"),
                rate=os.getenv("TTS_RATE", "-10%"),
                pitch=os.getenv("TTS_PITCH", "0%"),
                target_language=lang,
                pronunciations_csv=os.getenv("PRONUNCIATIONS_CSV", "./pronunciations.csv")
            )

        # Run TTS in parallel
        with ThreadPoolExecutor(max_workers=len(languages)) as executor:
            future_to_lang = {executor.submit(generate_tts_language, lang): lang for lang in languages}
            for future in as_completed(future_to_lang):
                lang = future_to_lang[future]
                try:
                    result = future.result()
                    storage.add_log(job_id, f"✓ {lang.upper()} TTS complete", "INFO")
                except Exception as e:
                    storage.add_log(job_id, f"✗ {lang.upper()} TTS failed: {e}", "ERROR")
                    raise

        # STEP 5: Enhance audio (SEQUENTIAL to avoid GPU overload)
        job.status = JobStatus.ENHANCING_AUDIO
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"STEP 5/6: Enhancing audio for {lang_display} (SEQUENTIAL)", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        for lang in languages:
            storage.add_log(job_id, f"Starting audio enhancement for {lang.upper()}...", "INFO")
            enhance_audio(job_id=job_id, target_language=lang)
            storage.add_log(job_id, f"✓ {lang.upper()} audio enhancement complete", "INFO")

        # STEP 6: Render final videos (SEQUENTIAL to avoid CPU/GPU overload)
        job.status = JobStatus.RENDERING
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, f"STEP 6/6: Rendering videos for {lang_display} (SEQUENTIAL)", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        final_videos = {}
        for lang in languages:
            storage.add_log(job_id, f"Starting video rendering for {lang.upper()}...", "INFO")
            render_result = render_final_video(
                job_id=job_id,
                target_language=lang,
                overlay_path=os.getenv("OVERLAY_PATH", "./assets/overlay.png"),
                loop_audio_path=os.getenv("LOOP_AUDIO_PATH", "./assets/loop.wav"),
                enable_background_music=job.enable_background_music
            )
            final_videos[lang] = render_result["final_video_path"]
            storage.add_log(job_id, f"✓ {lang.upper()} video rendering complete", "INFO")

        # DONE
        job.status = JobStatus.DONE
        job.completed_at = datetime.utcnow()
        storage.update_progress(job_id, "done", 6, message="Processing complete!")
        storage.save_job_state(job)

        storage.add_log(job_id, "=" * 60, "INFO")
        storage.add_log(job_id, "✅ PIPELINE COMPLETE!", "INFO")
        for lang, video_path in final_videos.items():
            storage.add_log(job_id, f"  [{lang.upper()}] {video_path}", "INFO")
        storage.add_log(job_id, "=" * 60, "INFO")

        return {
            "status": "success",
            "job_id": job_id,
            "final_videos": final_videos
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
