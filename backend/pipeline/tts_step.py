"""
Pipeline Step 4: Generate SSML and TTS audio
- Apply phonetics rules from CSV (Polish only)
- Generate SSML with <sub> and <phoneme> tags
- Run Azure TTS batch synthesis
- Apply studio-quality audio post-processing (optional)
Idempotent: Skips if tts_{language}.wav already exists
"""
from pathlib import Path
from backend.services.phonetics import PhoneticsService
from backend.services.azure_tts_batch import AzureTTSBatchService
from backend.services.audio_postprocessing import get_audio_postprocessing
from backend.services.storage import get_storage


def generate_tts(
    job_id: str,
    speech_key: str,
    speech_region: str,
    voice: str = "en-GB-OllieMultilingualNeural",
    rate: str = "-10%",
    pitch: str = "0%",
    target_language: str = "pl",
    pronunciations_csv: str = "./pronunciations.csv"
) -> dict:
    """
    Generate TTS audio with phonetics for target language

    Args:
        job_id: Job identifier
        speech_key: Azure Speech API key
        speech_region: Azure Speech region
        voice: Azure TTS voice name
        rate: Speech rate adjustment
        pitch: Speech pitch adjustment
        target_language: Target language code (pl, fr, en)
        pronunciations_csv: Path to pronunciations CSV (Polish only)

    Returns:
        dict with ssml_path, tts_audio_path
    """
    storage = get_storage()

    # Language display names
    lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
    lang_name = lang_names.get(target_language, target_language.upper())

    transcript_path = storage.get_artifact_path(job_id, f"transcript_{target_language}.txt")
    ssml_path = storage.get_artifact_path(job_id, f"ssml_{target_language}.xml")
    tts_audio_path = storage.get_artifact_path(job_id, f"tts_{target_language}.wav")

    # Check if TTS already done
    if storage.artifact_exists(job_id, f"tts_{target_language}.wav"):
        storage.add_log(job_id, f"{lang_name} TTS audio already exists, skipping", "INFO")
        return {
            "ssml_path": str(ssml_path) if ssml_path.exists() else None,
            "tts_audio_path": str(tts_audio_path)
        }

    # Check if translation exists
    if not transcript_path.exists():
        raise RuntimeError(f"{lang_name} transcript not found. Run translate step first.")

    storage.update_progress(job_id, "generating_tts", 4, message=f"Generating {lang_name} TTS...")
    storage.add_log(job_id, f"[{target_language.upper()}] Starting TTS generation...", "INFO")

    # Load translated text
    translated_text = transcript_path.read_text(encoding="utf-8")

    # Apply phonetics (Polish only)
    if target_language == "pl":
        storage.add_log(job_id, f"[{target_language.upper()}] Applying phonetics rules...", "INFO")
        phonetics = PhoneticsService(csv_path=pronunciations_csv)
        text_with_ssml = phonetics.inject_ssml_tags(translated_text)

        # Validate SSML
        is_valid, error = phonetics.validate_ssml(text_with_ssml)
        if not is_valid:
            storage.add_log(job_id, f"⚠ SSML validation warning: {error}", "WARNING")

        # Get statistics
        stats = phonetics.get_statistics(text_with_ssml)
        storage.add_log(
            job_id,
            f"[{target_language.upper()}] Applied phonetics: {stats['sub_tags']} substitutions, {stats['phoneme_tags']} phonemes",
            "INFO"
        )

        # Save SSML for reference
        ssml_path.write_text(text_with_ssml, encoding="utf-8")
        storage.mark_step_complete(job_id, f"ssml_{target_language}", str(ssml_path))
    else:
        # No phonetics for French/English, use plain text
        text_with_ssml = translated_text
        storage.add_log(job_id, f"[{target_language.upper()}] Skipping phonetics (not available for {lang_name})", "INFO")

    # Generate TTS
    storage.update_progress(job_id, "generating_tts", 4, message=f"Synthesizing {lang_name} speech...")
    storage.add_log(job_id, f"[{target_language.upper()}] Starting Azure TTS synthesis (voice: {voice})...", "INFO")

    tts_service = AzureTTSBatchService(
        speech_key=speech_key,
        speech_region=speech_region,
        voice=voice,
        rate=rate,
        pitch=pitch,
        target_language=target_language
    )

    def progress_callback(current, total, message):
        """Update progress during TTS generation"""
        storage.add_log(job_id, f"[{target_language.upper()}] [TTS {current}/{total}] {message}", "INFO")

    try:
        tts_service.generate_audio(
            text=text_with_ssml,
            output_wav=tts_audio_path,
            progress_callback=progress_callback
        )

        storage.mark_step_complete(job_id, f"tts_{target_language}", str(tts_audio_path))

        # Get audio duration
        duration = tts_audio_path.stat().st_size / (48000 * 2 * 2)  # Rough estimate
        storage.add_log(job_id, f"[{target_language.upper()}] ✓ TTS audio generated: {tts_audio_path.name} (~{duration:.1f}s)", "INFO")

        return {
            "ssml_path": str(ssml_path) if ssml_path.exists() else None,
            "tts_audio_path": str(tts_audio_path),
            "language": target_language
        }

    except Exception as e:
        storage.add_log(job_id, f"[{target_language.upper()}] ✗ TTS generation failed: {e}", "ERROR")
        raise RuntimeError(f"{lang_name} TTS generation failed: {e}")
