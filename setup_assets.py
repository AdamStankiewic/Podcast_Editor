#!/usr/bin/env python3
"""
Setup script to generate placeholder assets
Creates overlay.png and loop.wav if they don't exist
"""
import subprocess
from pathlib import Path


def create_overlay_png():
    """Create transparent placeholder overlay PNG using ffmpeg"""
    overlay_path = Path("assets/overlay.png")

    if overlay_path.exists():
        print(f"✓ Overlay already exists: {overlay_path}")
        return

    print("Creating placeholder overlay.png...")

    # Create a transparent 1920x1080 PNG with a border frame
    # Using ffmpeg to generate a test pattern
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=black@0.0:s=1920x1080:d=1",  # Transparent background
            "-frames:v", "1",
            str(overlay_path)
        ], check=True, capture_output=True)

        print(f"✓ Created transparent overlay: {overlay_path}")
        print("  Note: Replace with your custom overlay PNG with alpha channel")

    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create overlay: {e}")
        print("  You can create it manually or skip if not needed")


def create_loop_wav():
    """Create placeholder background music loop using ffmpeg"""
    loop_path = Path("assets/loop.wav")

    if loop_path.exists():
        print(f"✓ Loop audio already exists: {loop_path}")
        return

    print("Creating placeholder loop.wav (10s silence)...")

    # Create 10 seconds of silence as placeholder
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo:d=10",
            "-c:a", "pcm_s16le",
            str(loop_path)
        ], check=True, capture_output=True)

        print(f"✓ Created placeholder loop: {loop_path}")
        print("  Note: Replace with your background music (will be looped)")

    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create loop audio: {e}")
        print("  You can create it manually or skip if not needed")


def main():
    """Main setup function"""
    print("=" * 60)
    print("PODCAST LANGUAGE CONVERTER - Asset Setup")
    print("=" * 60)

    # Create assets directory if not exists
    Path("assets").mkdir(exist_ok=True)

    # Create placeholder files
    create_overlay_png()
    create_loop_wav()

    print("\n" + "=" * 60)
    print("✅ Asset setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Replace assets/overlay.png with your custom frame (PNG with alpha)")
    print("2. Replace assets/loop.wav with your background music")
    print("3. Edit pronunciations.csv with your custom pronunciation rules")
    print("\nRun: docker-compose up -d")


if __name__ == "__main__":
    main()
