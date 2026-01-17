"""
Test Audio Enhancement Script
Pozwala przetestować audio post-processing na istniejącym pliku TTS
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.audio_postprocessing import AudioPostProcessingService


def test_enhancement(job_id: str):
    """
    Test audio enhancement on existing TTS file

    Args:
        job_id: Job ID to test (folder name in data/)
    """
    print(f"Testing audio enhancement for job: {job_id}\n")

    # Paths
    data_dir = Path(__file__).parent / "data" / job_id
    input_wav = data_dir / "tts.wav"
    output_wav = data_dir / "tts_test_enhanced.wav"

    # Check if input exists
    if not input_wav.exists():
        print(f"❌ Input file not found: {input_wav}")
        return

    print(f"✓ Input file: {input_wav}")
    print(f"✓ Output file: {output_wav}\n")

    # Create audio post-processing service
    audio_pp = AudioPostProcessingService(
        enable_ai_enhance=True,   # Try Resemble Enhance first
        enable_denoise=True,      # Use DeepFilterNet if Resemble not available
        enable_studio_chain=True, # EQ + Compression + Limiter
        target_lufs=-16.0         # Podcast standard
    )

    print("\n" + "="*60)
    print("Starting audio enhancement...")
    print("="*60 + "\n")

    def progress_callback(current, total, message):
        print(f"[{current}/{total}] {message}")

    try:
        # Process audio
        audio_pp.process_audio(
            input_wav=input_wav,
            output_wav=output_wav,
            progress_callback=progress_callback
        )

        print("\n" + "="*60)
        print("✅ Enhancement complete!")
        print("="*60)
        print(f"\nCompare these files in VLC Player:")
        print(f"  Original: {input_wav}")
        print(f"  Enhanced: {output_wav}")
        print("\nYou should hear:")
        print("  - Cleaner sound (less noise)")
        print("  - More presence and clarity")
        print("  - Better dynamics (compression)")
        print("  - Consistent volume (LUFS normalization)")

    except Exception as e:
        print(f"\n❌ Enhancement failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python test_audio_enhancement.py <job_id>")
        print("\nAvailable jobs:")
        data_dir = Path(__file__).parent / "data"
        if data_dir.exists():
            jobs = [d.name for d in data_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
            for job in jobs:
                tts_file = data_dir / job / "tts.wav"
                if tts_file.exists():
                    size_mb = tts_file.stat().st_size / (1024 * 1024)
                    print(f"  - {job} ({size_mb:.1f} MB)")
        sys.exit(1)

    job_id = sys.argv[1]
    test_enhancement(job_id)
