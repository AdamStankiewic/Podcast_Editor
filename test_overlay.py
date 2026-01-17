#!/usr/bin/env python3
"""
Quick overlay test script
Tests if overlay rendering works without running full pipeline
"""
import subprocess
import sys
from pathlib import Path


def test_overlay(job_id: str):
    """Test overlay rendering on existing job"""

    data_dir = Path(__file__).parent / "data" / job_id
    assets_dir = Path(__file__).parent / "assets"

    # Check required files - try multiple video sources
    base_video = None
    for video_name in ["base_video.mp4", "original.mp4", "final.mp4"]:
        video_path = data_dir / video_name
        if video_path.exists():
            base_video = video_path
            print(f"✓ Found video: {video_name}")
            break

    if not base_video:
        print(f"❌ No video found in {data_dir}")
        print(f"   Looked for: base_video.mp4, original.mp4, final.mp4")
        return False

    # Overlay from assets folder
    overlay_png = assets_dir / "overlay.png"
    output_video = data_dir / "test_overlay.mp4"

    if not overlay_png.exists():
        print(f"❌ Overlay PNG not found: {overlay_png}")
        return False

    print(f"✓ Base video: {base_video}")
    print(f"✓ Overlay PNG: {overlay_png}")
    print(f"✓ Output: {output_video}")
    print()

    # Get video info
    print("Checking base video info...")
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "default=noprint_wrappers=1",
        str(base_video)
    ]

    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    print(result.stdout)

    # Get video dimensions
    try:
        import json
        probe_result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(base_video)
        ], capture_output=True, text=True, check=True)

        video_info = json.loads(probe_result.stdout)
        video_width = video_info["streams"][0]["width"]
        video_height = video_info["streams"][0]["height"]
        print(f"Video dimensions: {video_width}x{video_height}")
    except Exception as e:
        print(f"Warning: Could not get video dimensions: {e}")
        video_width = 2560
        video_height = 1440

    # Render overlay
    print("Rendering overlay with 7% video scale-up...")
    print("(This will take ~10 seconds)")
    print()

    # Use same filter as production code - scale up 7%, crop to original size, overlay
    filter_complex = (
        f"[0:v]scale=iw*1.07:ih*1.07,crop={video_width}:{video_height}:(iw-{video_width})/2:(ih-{video_height})/2,setpts=1.0*PTS[v];"
        "[v][1:v]overlay=0:0:format=auto:shortest=1"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(base_video),
        "-loop", "1",
        "-i", str(overlay_png),
        "-filter_complex", filter_complex,
        "-an",  # No audio for quick test
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",  # Force standard pixel format for Windows compatibility
        "-t", "10",  # Only first 10 seconds for quick test
        str(output_video)
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"✅ Overlay test complete!")
        print()
        print(f"Output file: {output_video}")
        print()
        print("Check the video:")
        print(f"  - Open in Windows: {output_video.as_posix().replace('/mnt/c/', 'C:/')}")
        print(f"  - The overlay should be visible at position 0:0 (top-left)")
        print()
        print("Video details:")

        # Show output info
        probe_cmd_out = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt,width,height",
            "-of", "default=noprint_wrappers=1",
            str(output_video)
        ]
        result = subprocess.run(probe_cmd_out, capture_output=True, text=True)
        print(result.stdout)

        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg error:")
        print(e.stderr.decode() if e.stderr else "Unknown error")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_overlay.py <job_id>")
        print()
        print("Example:")
        print("  python test_overlay.py 564fcfbe-e4a0-4dee-b2cd-f35d7ddc1f13")
        sys.exit(1)

    job_id = sys.argv[1]
    print(f"Testing overlay for job: {job_id}")
    print()

    success = test_overlay(job_id)
    sys.exit(0 if success else 1)
