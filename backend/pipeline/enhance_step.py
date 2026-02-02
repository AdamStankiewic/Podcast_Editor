"""
Pipeline Step 5: Enhance TTS audio quality
- Apply Resemble Enhance AI voice enhancement
- Apply EQ, compression, and LUFS normalization
Idempotent: Skips if enhanced_{language}.wav already exists
"""
from pathlib import Path
from backend.services.audio_postprocessing import get_audio_postprocessing
from backend.services.storage import get_storage


def enhance_audio(
    job_id: str,
    target_language: str = "pl"
) -> dict:
    """
    Enhance TTS audio with AI processing and studio chain

    Args:
        job_id: Job identifier
        target_language: Target language code (pl, fr, en)

    Returns:
        dict with enhanced_audio_path
    """
    storage = get_storage()

    # Language display names
    lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
    lang_name = lang_names.get(target_language, target_language.upper())

    tts_audio_path = storage.get_artifact_path(job_id, f"tts_{target_language}.wav")
    enhanced_audio_path = storage.get_artifact_path(job_id, f"enhanced_{target_language}.wav")

    # Check if already enhanced
    if storage.artifact_exists(job_id, f"enhanced_{target_language}.wav"):
        storage.add_log(job_id, f"[{target_language.upper()}] Enhanced audio already exists, skipping", "INFO")
        return {"enhanced_audio_path": str(enhanced_audio_path)}

    # Check if TTS audio exists
    if not tts_audio_path.exists():
        raise RuntimeError(f"{lang_name} TTS audio not found. Run TTS step first.")

    storage.update_progress(job_id, "enhancing_audio", 5, message=f"Enhancing {lang_name} audio...")
    storage.add_log(job_id, f"[{target_language.upper()}] Starting audio enhancement (Resemble Enhance + loudnorm)...", "INFO")

    def progress_callback(current, total, message):
        """Update progress during audio enhancement"""
        storage.add_log(job_id, f"[{target_language.upper()}] [Enhance {current}/{total}] {message}", "INFO")

    try:
        audio_postprocessing = get_audio_postprocessing(
            enable_ai_enhance=True,  # Enable Resemble Enhance (AI voice enhancement)
            enable_denoise=True,  # Enable DeepFilterNet if Resemble not available
            enable_studio_chain=False,  # Skip EQ/compression - Resemble Enhance is enough
            target_lufs=-17.0  # Quieter, natural podcast level
        )

        audio_postprocessing.process_audio(
            input_wav=tts_audio_path,
            output_wav=enhanced_audio_path,
            progress_callback=progress_callback
        )

        storage.mark_step_complete(job_id, f"enhanced_{target_language}", str(enhanced_audio_path))
        storage.add_log(job_id, f"[{target_language.upper()}] ✓ Audio enhancement complete: {enhanced_audio_path.name}", "INFO")

        return {"enhanced_audio_path": str(enhanced_audio_path)}

    except Exception as e:
        storage.add_log(job_id, f"[{target_language.upper()}] ✗ Audio enhancement failed: {e}", "ERROR")
        raise RuntimeError(f"{lang_name} audio enhancement failed: {e}")
