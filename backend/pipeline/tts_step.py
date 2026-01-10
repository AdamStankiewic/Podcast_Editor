"""
Pipeline Step 4: Generate SSML and TTS audio
- Apply phonetics rules from CSV
- Generate SSML with <sub> and <phoneme> tags
- Run Azure TTS batch synthesis
Idempotent: Skips if tts.wav already exists
"""
from pathlib import Path
from backend.services.phonetics import PhoneticsService
from backend.services.azure_tts_batch import AzureTTSBatchService
from backend.services.storage import get_storage


def generate_tts(
    job_id: str,
    speech_key: str,
    speech_region: str,
    voice: str = "en-GB-Ollie:DragonHDLatestNeural",
    rate: str = "-8%",
    pitch: str = "0%",
    pronunciations_csv: str = "./pronunciations.csv"
) -> dict:
    """
    Generate TTS audio with phonetics

    Returns:
        dict with ssml_path, tts_audio_path, phonetics_stats
    """
    storage = get_storage()

    transcript_pl_path = storage.get_artifact_path(job_id, "transcript_pl.txt")
    ssml_path = storage.get_artifact_path(job_id, "ssml_pl.xml")
    tts_audio_path = storage.get_artifact_path(job_id, "tts.wav")

    # Check if TTS already done
    if storage.artifact_exists(job_id, "tts.wav"):
        storage.add_log(job_id, "TTS audio already exists, skipping", "INFO")
        return {
            "ssml_path": str(ssml_path) if ssml_path.exists() else None,
            "tts_audio_path": str(tts_audio_path)
        }

    # Check if Polish transcript exists
    if not transcript_pl_path.exists():
        raise RuntimeError("Polish transcript not found. Run translate step first.")

    storage.update_progress(job_id, "generating_tts", 4, message="Applying phonetics rules...")
    storage.add_log(job_id, "Loading phonetics rules...", "INFO")

    # Load Polish text
    text_pl = transcript_pl_path.read_text(encoding="utf-8")

    # Apply phonetics
    phonetics = PhoneticsService(csv_path=pronunciations_csv)
    text_with_ssml = phonetics.inject_ssml_tags(text_pl)

    # Validate SSML
    is_valid, error = phonetics.validate_ssml(text_with_ssml)
    if not is_valid:
        storage.add_log(job_id, f"⚠ SSML validation warning: {error}", "WARNING")

    # Get statistics
    stats = phonetics.get_statistics(text_with_ssml)
    storage.add_log(
        job_id,
        f"Applied phonetics: {stats['sub_tags']} substitutions, {stats['phoneme_tags']} phonemes",
        "INFO"
    )

    # Save SSML for reference
    ssml_path.write_text(text_with_ssml, encoding="utf-8")
    storage.mark_step_complete(job_id, "ssml_pl", str(ssml_path))

    # Generate TTS
    storage.update_progress(job_id, "generating_tts", 4, message="Synthesizing speech with Azure TTS...")
    storage.add_log(job_id, f"Starting Azure TTS synthesis (voice: {voice})...", "INFO")

    tts_service = AzureTTSBatchService(
        speech_key=speech_key,
        speech_region=speech_region,
        voice=voice,
        rate=rate,
        pitch=pitch
    )

    def progress_callback(current, total, message):
        """Update progress during TTS generation"""
        storage.add_log(job_id, f"[TTS {current}/{total}] {message}", "INFO")

    try:
        tts_service.generate_audio(
            text=text_with_ssml,
            output_wav=tts_audio_path,
            progress_callback=progress_callback
        )

        storage.mark_step_complete(job_id, "tts_audio", str(tts_audio_path))

        # Get audio duration
        duration = tts_audio_path.stat().st_size / (48000 * 2 * 2)  # Rough estimate
        storage.add_log(job_id, f"✓ TTS audio generated: {tts_audio_path.name}", "INFO")

        return {
            "ssml_path": str(ssml_path),
            "tts_audio_path": str(tts_audio_path),
            "phonetics_stats": stats
        }

    except Exception as e:
        storage.add_log(job_id, f"✗ TTS generation failed: {e}", "ERROR")
        raise RuntimeError(f"TTS generation failed: {e}")
