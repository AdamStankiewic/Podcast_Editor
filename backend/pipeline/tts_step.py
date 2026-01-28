"""
Pipeline Step 4: Generate TTS audio
- Supports multiple TTS providers: Chatterbox (primary), Azure (fallback)
- Apply phonetics rules from CSV (text replacement for Chatterbox, SSML for Azure)
- Generate high-quality podcast audio
Idempotent: Skips if tts_{language}.wav already exists
"""
import os
from pathlib import Path
from backend.services.phonetics import PhoneticsService
from backend.services.tts_provider import (
    TTSProviderType,
    TTSConfig,
    get_tts_provider
)
from backend.services.storage import get_storage


def generate_tts(
    job_id: str,
    target_language: str = "pl",
    pronunciations_csv: str = "./pronunciations.csv",
    # Provider selection
    tts_provider: str = None,  # "chatterbox" or "azure", None = use env default
    # Chatterbox-specific
    reference_audio: str = None,
    exaggeration: float = None,
    cfg_weight: float = None,
    # Azure-specific (fallback)
    speech_key: str = None,
    speech_region: str = None,
    voice: str = None,
    rate: str = None,
    pitch: str = None
) -> dict:
    """
    Generate TTS audio with phonetics for target language

    Args:
        job_id: Job identifier
        target_language: Target language code (pl, fr, en)
        pronunciations_csv: Path to pronunciations CSV

        # Provider selection
        tts_provider: "chatterbox" (default) or "azure"

        # Chatterbox options
        reference_audio: Path to voice reference audio for cloning
        exaggeration: Emotion level 0.0-1.0 (default 0.4 for podcasts)
        cfg_weight: CFG weight 0.0-1.0 (default 0.5)

        # Azure options (fallback)
        speech_key: Azure Speech API key
        speech_region: Azure Speech region
        voice: Azure TTS voice name
        rate: Speech rate adjustment
        pitch: Speech pitch adjustment

    Returns:
        dict with tts_audio_path, provider, metadata
    """
    storage = get_storage()

    # Language display names
    lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
    lang_name = lang_names.get(target_language, target_language.upper())

    transcript_path = storage.get_artifact_path(job_id, f"transcript_{target_language}.txt")
    tts_audio_path = storage.get_artifact_path(job_id, f"tts_{target_language}.wav")

    # Check if TTS already done
    if storage.artifact_exists(job_id, f"tts_{target_language}.wav"):
        storage.add_log(job_id, f"{lang_name} TTS audio already exists, skipping", "INFO")
        return {
            "tts_audio_path": str(tts_audio_path),
            "language": target_language,
            "skipped": True
        }

    # Check if translation exists
    if not transcript_path.exists():
        raise RuntimeError(f"{lang_name} transcript not found. Run translate step first.")

    storage.update_progress(job_id, "generating_tts", 4, message=f"Generating {lang_name} TTS...")
    storage.add_log(job_id, f"[{target_language.upper()}] Starting TTS generation...", "INFO")

    # Load translated text
    translated_text = transcript_path.read_text(encoding="utf-8")

    # Determine provider (env default or parameter)
    provider_name = tts_provider or os.getenv("TTS_PROVIDER", "chatterbox")
    provider_type = TTSProviderType(provider_name.lower())

    storage.add_log(job_id, f"[{target_language.upper()}] Using TTS provider: {provider_name}", "INFO")

    # Apply phonetics based on provider
    phonetics = PhoneticsService(csv_path=pronunciations_csv)

    if provider_type == TTSProviderType.CHATTERBOX:
        # Chatterbox: Use simple text replacements (no SSML)
        if target_language == "pl" and phonetics.rules:
            text_for_tts, replacements = phonetics.apply_text_replacements(translated_text)
            storage.add_log(
                job_id,
                f"[{target_language.upper()}] Applied {replacements} pronunciation replacements",
                "INFO"
            )
        else:
            text_for_tts = translated_text
            storage.add_log(
                job_id,
                f"[{target_language.upper()}] No pronunciation rules for {lang_name}",
                "INFO"
            )

        # Build Chatterbox config
        # Optimized for storytelling/podcast narration style
        config = TTSConfig(
            voice=reference_audio or os.getenv("CHATTERBOX_REFERENCE_AUDIO", ""),
            target_language=target_language,
            # Slower rate for storytelling (0.9 = 10% slower)
            rate=float(os.getenv("CHATTERBOX_RATE", "0.9")),
            # Higher exaggeration for more expressive narration (0.5 default)
            exaggeration=exaggeration if exaggeration is not None else float(os.getenv("CHATTERBOX_EXAGGERATION", "0.5")),
            cfg_weight=cfg_weight if cfg_weight is not None else float(os.getenv("CHATTERBOX_CFG_WEIGHT", "0.5"))
        )

        # Get provider
        model_variant = os.getenv("CHATTERBOX_MODEL", "multilingual")
        provider = get_tts_provider(
            provider_type,
            model_variant=model_variant,
            reference_audio_path=config.voice if config.voice else None
        )

        storage.add_log(
            job_id,
            f"[{target_language.upper()}] Chatterbox config: model={model_variant}, rate={config.rate}, exaggeration={config.exaggeration}, cfg_weight={config.cfg_weight}",
            "INFO"
        )

    else:  # Azure fallback
        # Azure: Use SSML injection for Polish
        if target_language == "pl":
            storage.add_log(job_id, f"[{target_language.upper()}] Applying SSML phonetics rules...", "INFO")
            text_for_tts = phonetics.inject_ssml_tags(translated_text)

            # Validate SSML
            is_valid, error = phonetics.validate_ssml(text_for_tts)
            if not is_valid:
                storage.add_log(job_id, f"SSML validation warning: {error}", "WARNING")

            stats = phonetics.get_statistics(text_for_tts)
            storage.add_log(
                job_id,
                f"[{target_language.upper()}] Applied SSML: {stats['sub_tags']} substitutions, {stats['phoneme_tags']} phonemes",
                "INFO"
            )

            # Save SSML for reference
            ssml_path = storage.get_artifact_path(job_id, f"ssml_{target_language}.xml")
            ssml_path.write_text(text_for_tts, encoding="utf-8")
            storage.mark_step_complete(job_id, f"ssml_{target_language}", str(ssml_path))
        else:
            text_for_tts = translated_text
            storage.add_log(job_id, f"[{target_language.upper()}] Skipping SSML (not available for {lang_name})", "INFO")

        # Build Azure config
        config = TTSConfig(
            voice=voice or os.getenv("TTS_VOICE", "en-GB-OllieMultilingualNeural"),
            target_language=target_language,
            azure_rate=rate or os.getenv("TTS_RATE", "-10%"),
            azure_pitch=pitch or os.getenv("TTS_PITCH", "0%"),
            azure_region=speech_region or os.getenv("SPEECH_REGION", "northeurope"),
            azure_key=speech_key or os.getenv("SPEECH_KEY", "")
        )

        # Get provider
        provider = get_tts_provider(
            provider_type,
            speech_key=config.azure_key,
            speech_region=config.azure_region
        )

        storage.add_log(
            job_id,
            f"[{target_language.upper()}] Azure TTS config: voice={config.voice}, rate={config.azure_rate}",
            "INFO"
        )

    # Progress callback
    def progress_callback(current, total, message):
        storage.add_log(job_id, f"[{target_language.upper()}] [TTS {current}/{total}] {message}", "INFO")

    # Generate audio
    try:
        storage.update_progress(job_id, "generating_tts", 4, message=f"Synthesizing {lang_name} speech...")

        result = provider.generate_audio(
            text=text_for_tts,
            output_path=tts_audio_path,
            config=config,
            progress_callback=progress_callback
        )

        storage.mark_step_complete(job_id, f"tts_{target_language}", str(tts_audio_path))

        storage.add_log(
            job_id,
            f"[{target_language.upper()}] TTS audio generated: {tts_audio_path.name} ({result.duration_seconds:.1f}s) via {result.provider.value}",
            "INFO"
        )

        return {
            "tts_audio_path": str(result.audio_path),
            "language": target_language,
            "provider": result.provider.value,
            "duration_seconds": result.duration_seconds,
            "metadata": result.metadata
        }

    except Exception as e:
        storage.add_log(job_id, f"[{target_language.upper()}] TTS generation failed: {e}", "ERROR")

        # Try fallback to Azure if Chatterbox failed
        if provider_type == TTSProviderType.CHATTERBOX:
            storage.add_log(job_id, f"[{target_language.upper()}] Attempting Azure TTS fallback...", "WARNING")
            try:
                return generate_tts(
                    job_id=job_id,
                    target_language=target_language,
                    pronunciations_csv=pronunciations_csv,
                    tts_provider="azure",
                    speech_key=speech_key or os.getenv("SPEECH_KEY"),
                    speech_region=speech_region,
                    voice=voice,
                    rate=rate,
                    pitch=pitch
                )
            except Exception as fallback_error:
                storage.add_log(job_id, f"[{target_language.upper()}] Azure fallback also failed: {fallback_error}", "ERROR")

        raise RuntimeError(f"{lang_name} TTS generation failed: {e}")
