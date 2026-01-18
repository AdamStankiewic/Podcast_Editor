"""
Pipeline Step 3: Translate German to target language
Uses OpenAI with context preservation and length matching
Idempotent: Skips if translation already exists
"""
from pathlib import Path
from backend.services.translate import TranslationService
from backend.services.storage import get_storage


def translate_transcript(job_id: str, openai_api_key: str = None, target_language: str = "pl") -> dict:
    """
    Translate German transcript to target language

    Args:
        job_id: Job identifier
        openai_api_key: OpenAI API key
        target_language: Target language code (pl, fr, en)

    Returns:
        dict with translation_path
    """
    storage = get_storage()

    # Language display names
    lang_names = {"pl": "Polish", "fr": "French", "en": "English"}
    lang_name = lang_names.get(target_language, target_language.upper())

    transcript_de_path = storage.get_artifact_path(job_id, "transcript_de.txt")
    translation_path = storage.get_artifact_path(job_id, f"transcript_{target_language}.txt")

    # Check if already translated
    if storage.artifact_exists(job_id, f"transcript_{target_language}.txt"):
        storage.add_log(job_id, f"{lang_name} translation already exists, skipping", "INFO")
        return {"translation_path": str(translation_path)}

    # Check if German transcript exists
    if not transcript_de_path.exists():
        raise RuntimeError("German transcript not found. Run transcribe step first.")

    storage.update_progress(job_id, "translating", 3, message=f"Translating to {lang_name}...")
    storage.add_log(job_id, f"Starting translation (DE → {target_language.upper()})...", "INFO")

    # Load German text
    text_de = transcript_de_path.read_text(encoding="utf-8")
    storage.add_log(job_id, f"German text: {len(text_de)} characters", "INFO")

    # Translate using service
    translator = TranslationService(api_key=openai_api_key, target_language=target_language)

    def progress_callback(current, total, message):
        """Update progress during translation"""
        storage.add_log(job_id, f"[{target_language.upper()}] [{current}/{total}] {message}", "INFO")

    try:
        translated_text = translator.translate(text_de, progress_callback=progress_callback)

        # Save translation
        translation_path.write_text(translated_text, encoding="utf-8")

        storage.mark_step_complete(job_id, f"transcript_{target_language}", str(translation_path))

        # Log statistics
        ratio = len(translated_text) / len(text_de)
        storage.add_log(job_id, f"✓ {lang_name} translation complete: {len(translated_text)} chars (ratio: {ratio:.2f})", "INFO")

        return {"translation_path": str(translation_path)}

    except Exception as e:
        storage.add_log(job_id, f"✗ {lang_name} translation failed: {e}", "ERROR")
        raise RuntimeError(f"{lang_name} translation failed: {e}")
