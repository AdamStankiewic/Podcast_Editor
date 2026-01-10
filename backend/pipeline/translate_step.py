"""
Pipeline Step 3: Translate German to Polish
Uses OpenAI with context preservation and length matching
Idempotent: Skips if transcript_pl.txt already exists
"""
from pathlib import Path
from backend.services.translate import TranslationService
from backend.services.storage import get_storage


def translate_transcript(job_id: str, openai_api_key: str = None) -> dict:
    """
    Translate German transcript to Polish

    Returns:
        dict with transcript_pl_path
    """
    storage = get_storage()

    transcript_de_path = storage.get_artifact_path(job_id, "transcript_de.txt")
    transcript_pl_path = storage.get_artifact_path(job_id, "transcript_pl.txt")

    # Check if already translated
    if storage.artifact_exists(job_id, "transcript_pl.txt"):
        storage.add_log(job_id, "Polish translation already exists, skipping", "INFO")
        return {"transcript_pl_path": str(transcript_pl_path)}

    # Check if German transcript exists
    if not transcript_de_path.exists():
        raise RuntimeError("German transcript not found. Run transcribe step first.")

    storage.update_progress(job_id, "translating", 3, message="Translating to Polish...")
    storage.add_log(job_id, "Starting translation (DE → PL)...", "INFO")

    # Load German text
    text_de = transcript_de_path.read_text(encoding="utf-8")
    storage.add_log(job_id, f"German text: {len(text_de)} characters", "INFO")

    # Translate using service
    translator = TranslationService(api_key=openai_api_key)

    def progress_callback(current, total, message):
        """Update progress during translation"""
        storage.add_log(job_id, f"[{current}/{total}] {message}", "INFO")

    try:
        text_pl = translator.translate(text_de, progress_callback=progress_callback)

        # Save Polish translation
        transcript_pl_path.write_text(text_pl, encoding="utf-8")

        storage.mark_step_complete(job_id, "transcript_pl", str(transcript_pl_path))

        # Log statistics
        ratio = len(text_pl) / len(text_de)
        storage.add_log(job_id, f"✓ Translation complete: {len(text_pl)} chars (ratio: {ratio:.2f})", "INFO")

        return {"transcript_pl_path": str(transcript_pl_path)}

    except Exception as e:
        storage.add_log(job_id, f"✗ Translation failed: {e}", "ERROR")
        raise RuntimeError(f"Translation failed: {e}")
