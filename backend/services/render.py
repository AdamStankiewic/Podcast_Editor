"""
Video rendering service using ffmpeg
Handles video montage: audio replacement, music loop, ducking, overlay, speed adjustment
"""
import subprocess
import json
from pathlib import Path
from typing import Optional


class VideoRenderService:
    """Handles final video rendering with Polish narration"""

    def __init__(
        self,
        overlay_path: str = "./assets/overlay.png",
        loop_audio_path: str = "./assets/loop.wav",
        use_gpu: bool = True  # NVENC acceleration
    ):
        self.overlay_path = Path(overlay_path)
        self.loop_audio_path = Path(loop_audio_path)
        self.use_gpu = use_gpu

        # Detect NVENC availability
        if self.use_gpu:
            self.encoder, self.preset = self._detect_gpu_encoder()
        else:
            self.encoder = "libx264"
            self.preset = "medium"

    def _detect_gpu_encoder(self) -> tuple[str, str]:
        """
        Detect available GPU encoder (NVENC, VideoToolbox, etc.)
        Returns (encoder, preset)
        """
        try:
            # Check if NVENC is available
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=5
            )

            encoders = result.stdout

            # Priority: NVENC (NVIDIA) > VideoToolbox (macOS) > CPU
            if "h264_nvenc" in encoders:
                print("✓ Detected NVIDIA NVENC - using GPU acceleration")
                return "h264_nvenc", "p4"  # p4 = medium quality preset
            elif "h264_videotoolbox" in encoders:
                print("✓ Detected VideoToolbox - using GPU acceleration")
                return "h264_videotoolbox", "medium"
            else:
                print("⚠ No GPU encoder detected - using CPU (libx264)")
                return "libx264", "medium"

        except Exception as e:
            print(f"⚠ GPU detection failed: {e}, falling back to CPU")
            return "libx264", "medium"

    def render_final_video(
        self,
        original_video: Path,
        tts_audio: Path,
        output_video: Path,
        progress_callback: Optional[callable] = None
    ) -> Path:
        """
        Render final video with:
        - Original video (speed-adjusted if needed)
        - Polish TTS narration
        - Background music loop with ducking
        - Overlay PNG frame

        Pipeline:
        1. Get video/audio durations
        2. Calculate speed adjustment ratio
        3. Create audio mix (TTS + music with ducking)
        4. Render video with speed adjustment + overlay
        5. Merge video + audio
        """
        # Use RAM Disk if configured for faster temp I/O
        import os
        temp_base = os.getenv("TEMP_PATH", str(output_video.parent))
        temp_dir = Path(temp_base) / f"_render_{output_video.stem}"
        temp_dir.mkdir(exist_ok=True, parents=True)

        try:
            # Step 1: Get durations
            if progress_callback:
                progress_callback(1, 6, "Analyzing video and audio...")

            video_duration = self._get_duration(original_video)
            audio_duration = self._get_duration(tts_audio)

            print(f"Video duration: {video_duration:.2f}s")
            print(f"Audio duration: {audio_duration:.2f}s")

            # Step 2: Calculate speed ratio
            if progress_callback:
                progress_callback(2, 6, "Calculating speed adjustment...")

            speed_ratio = self._calculate_speed_ratio(video_duration, audio_duration)
            print(f"Speed ratio: {speed_ratio:.3f}x")

            # Step 3: Create background music loop
            if progress_callback:
                progress_callback(3, 6, "Creating music loop...")

            music_loop = temp_dir / "music_loop.wav"
            self._create_music_loop(audio_duration, music_loop)

            # Step 4: Mix audio with ducking
            if progress_callback:
                progress_callback(4, 6, "Mixing audio with ducking...")

            mixed_audio = temp_dir / "mixed_audio.wav"
            self._mix_audio_with_ducking(tts_audio, music_loop, mixed_audio)

            # Step 5: Process video (speed + overlay)
            if progress_callback:
                progress_callback(5, 6, "Processing video with speed adjustment...")

            processed_video = temp_dir / "video_processed.mp4"
            self._process_video(original_video, processed_video, speed_ratio)

            # Step 6: Merge video + audio
            if progress_callback:
                progress_callback(6, 6, "Merging final video...")

            self._merge_video_audio(processed_video, mixed_audio, output_video)

            # Cleanup
            import shutil
            shutil.rmtree(temp_dir)

            return output_video

        except Exception as e:
            # Cleanup on error
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise RuntimeError(f"Video rendering failed: {e}")

    def _get_duration(self, media_file: Path) -> float:
        """Get media file duration using ffprobe"""
        try:
            result = subprocess.run([
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(media_file)
            ], capture_output=True, text=True, check=True)

            data = json.loads(result.stdout)
            return float(data["format"]["duration"])

        except Exception as e:
            raise RuntimeError(f"Failed to get duration for {media_file}: {e}")

    def _verify_video_stream(self, video_file: Path) -> bool:
        """Verify that video file has a valid video stream"""
        try:
            result = subprocess.run([
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                str(video_file)
            ], capture_output=True, text=True, check=True)

            data = json.loads(result.stdout)
            has_video = len(data.get("streams", [])) > 0

            if has_video:
                print(f"✓ Video stream verified in {video_file.name}")
            else:
                print(f"✗ No video stream found in {video_file.name}")

            return has_video

        except Exception as e:
            print(f"Warning: Failed to verify video stream: {e}")
            return False

    def _calculate_speed_ratio(self, video_duration: float, audio_duration: float) -> float:
        """
        Calculate speed ratio to match video to audio length
        Returns: ratio where 1.0 = no change, 2.0 = 2x speed, 0.5 = 0.5x speed

        Note: Wider range (0.5x to 3.5x) to accommodate translation length variations
        """
        ratio = audio_duration / video_duration

        # Clamp to reasonable range (0.5x to 3.5x)
        # Increased upper limit from 2.0x to handle shorter translations
        if ratio < 0.5:
            print(f"Warning: Speed ratio {ratio:.2f} is very slow, clamping to 0.5x")
            ratio = 0.5
        elif ratio > 3.5:
            print(f"Warning: Speed ratio {ratio:.2f} is very fast, clamping to 3.5x")
            ratio = 3.5
        elif ratio > 1.5:
            print(f"Info: Speed ratio {ratio:.2f}x - video will be noticeably faster")

        return ratio

    def _create_music_loop(self, target_duration: float, output_wav: Path):
        """Create looped background music for target duration"""
        if not self.loop_audio_path.exists():
            print(f"Warning: Loop audio not found at {self.loop_audio_path}, creating silence")
            # Create silence as fallback
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=r=48000:cl=stereo:d={target_duration}",
                str(output_wav)
            ], check=True, capture_output=True)
            return

        try:
            # Loop music to match duration, fade in/out for smooth loop
            subprocess.run([
                "ffmpeg", "-y",
                "-stream_loop", "-1",  # Infinite loop
                "-i", str(self.loop_audio_path),
                "-t", str(target_duration),
                "-af", "afade=t=in:st=0:d=1,afade=t=out:st=" + str(target_duration - 1) + ":d=1",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create music loop: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _mix_audio_with_ducking(self, tts_audio: Path, music_audio: Path, output_wav: Path):
        """
        Mix TTS and music with sidechain ducking
        Music volume automatically reduces when TTS is speaking
        """
        try:
            # Sidechain compression setup:
            # - TTS is main audio (index 0)
            # - Music is background (index 1)
            # - Music gets compressed when TTS has signal
            filter_complex = (
                # Lower music base volume to -24dB (quieter than before)
                "[1:a]volume=-24dB[music_low];"
                # Apply sidechain compression (music ducks under voice)
                "[music_low][0:a]sidechaincompress="
                "threshold=0.02:ratio=6:attack=5:release=250:makeup=2[bg];"
                # Mix voice + ducked music (reduced music weight from 0.4 to 0.15)
                "[0:a][bg]amix=inputs=2:duration=longest:weights=1.0 0.15[out]"
            )

            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(tts_audio),
                "-i", str(music_audio),
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "pcm_s16le",  # PCM for quality
                "-ar", "48000",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Audio mixing failed: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _process_video(self, input_video: Path, output_video: Path, speed_ratio: float):
        """
        Process video with:
        - Speed adjustment (setpts)
        - Overlay PNG frame
        - Remove original audio
        """
        print(f"Processing video: {input_video}")
        print(f"Output video: {output_video}")
        print(f"Speed ratio: {speed_ratio:.3f}x")

        # Calculate setpts value (inverse of speed ratio)
        # speed 2.0x = setpts 0.5 (PTS/2)
        # speed 0.5x = setpts 2.0 (PTS*2)
        setpts_value = 1.0 / speed_ratio

        # Build filter complex
        filters = []

        # Speed adjustment
        filters.append(f"setpts={setpts_value}*PTS")

        # Overlay if exists
        if self.overlay_path.exists():
            # Overlay syntax: [video][overlay]overlay=x:y
            # We'll do this separately since it needs two inputs
            has_overlay = True
            overlay_size = self.overlay_path.stat().st_size
            print(f"Using overlay: {self.overlay_path}")
            print(f"Overlay file size: {overlay_size / 1024:.2f} KB")

            # Get overlay dimensions using ffprobe
            try:
                probe_result = subprocess.run([
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,pix_fmt",
                    "-of", "json",
                    str(self.overlay_path)
                ], capture_output=True, text=True, check=True, timeout=5)

                overlay_info = json.loads(probe_result.stdout)
                if overlay_info.get("streams"):
                    stream = overlay_info["streams"][0]
                    print(f"Overlay dimensions: {stream.get('width')}x{stream.get('height')}, format: {stream.get('pix_fmt')}")
            except Exception as e:
                print(f"Warning: Could not probe overlay dimensions: {e}")
        else:
            has_overlay = False
            print(f"No overlay found at {self.overlay_path} (absolute: {self.overlay_path.absolute()})")
            print(f"Rendering without overlay")

        if has_overlay:
            try:
                # Get video dimensions for overlay scaling
                video_width = 2560  # Default
                video_height = 1440  # Default

                try:
                    probe_result = subprocess.run([
                        "ffprobe",
                        "-v", "error",
                        "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "json",
                        str(input_video)
                    ], capture_output=True, text=True, check=True, timeout=5)

                    video_info = json.loads(probe_result.stdout)
                    if video_info.get("streams"):
                        video_width = video_info["streams"][0].get("width", 2560)
                        video_height = video_info["streams"][0].get("height", 1440)
                        print(f"Video dimensions: {video_width}x{video_height}")
                except Exception as e:
                    print(f"Warning: Could not probe video dimensions: {e}, using defaults")

                # Two-input filter: video + overlay
                # NEW: Use simple scale instead of deprecated scale2ref
                # This works with FFmpeg 2025
                # Strategy: Scale video up 7%, crop to original size (fills frame better under overlay), then overlay
                filter_complex = (
                    # Scale video up by 7% to fill frame better, crop back to original size (centered), apply speed
                    f"[0:v]scale=iw*1.07:ih*1.07,crop={video_width}:{video_height}:(iw-{video_width})/2:(ih-{video_height})/2,setpts={setpts_value}*PTS[v];"
                    # Overlay PNG on top at position 0:0 (top-left corner)
                    # repeatlast=1 means repeat the last (only) frame of overlay throughout video
                    # format=auto automatically handles alpha channel (RGBA)
                    f"[v][1:v]overlay=0:0:format=auto:repeatlast=1"
                )

                print(f"Using filter: {filter_complex}")

                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_video),
                    "-i", str(self.overlay_path),  # Overlay PNG (no -loop needed with repeatlast=1)
                    "-filter_complex", filter_complex,
                    "-an",  # Remove audio
                    "-c:v", self.encoder,
                    "-preset", self.preset,
                    "-crf", "23" if self.encoder == "libx264" else "20",  # Lower CRF for NVENC
                    "-pix_fmt", "yuv420p",  # Force standard pixel format for compatibility
                    str(output_video)
                ]

                print(f"Video processing command (with overlay): {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True)

                # Show FFmpeg output (both stdout and stderr)
                if result.stdout:
                    print(f"FFmpeg overlay stdout: {result.stdout[-500:]}")
                if result.stderr:
                    print(f"FFmpeg overlay stderr (last 2000 chars): {result.stderr[-2000:]}")

                # Check if FFmpeg succeeded
                if result.returncode != 0:
                    print(f"FFmpeg overlay processing failed with return code {result.returncode}")
                    raise RuntimeError(f"FFmpeg failed: {result.stderr[-500:]}")

                # Verify video stream exists in output
                if not self._verify_video_stream(output_video):
                    print(f"ERROR: video_processed.mp4 has no video stream! Retrying without overlay...")
                    raise RuntimeError("Video stream missing after overlay processing")

                print(f"✓ Video processed with overlay successfully: {output_video}")

            except (subprocess.CalledProcessError, RuntimeError) as e:
                error_msg = str(e)
                if hasattr(e, 'stderr') and e.stderr:
                    error_msg = e.stderr.decode() if hasattr(e.stderr, 'decode') else str(e.stderr)

                print(f"OVERLAY PROCESSING FAILED: {error_msg}")
                print(f"Falling back to video without overlay...")

                # Fallback: render without overlay
                has_overlay = False

        # If overlay failed or not used, render without overlay
        if not has_overlay:
            try:
                # Simple speed adjustment without overlay
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(input_video),
                    "-vf", f"setpts={setpts_value}*PTS",
                    "-an",  # Remove audio
                    "-c:v", self.encoder,
                    "-preset", self.preset,
                    "-crf", "23" if self.encoder == "libx264" else "20",  # Lower CRF for NVENC
                    "-pix_fmt", "yuv420p",  # Force standard pixel format for compatibility
                    str(output_video)
                ]

                print(f"Video processing command (no overlay): {' '.join(cmd)}")
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)

                if result.stderr:
                    print(f"FFmpeg video processing stderr: {result.stderr[-500:]}")  # Last 500 chars

                print(f"Video processed successfully: {output_video} (exists: {Path(output_video).exists()})")

            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode() if hasattr(e.stderr, 'decode') else str(e.stderr)
                print(f"VIDEO PROCESSING ERROR: {error_msg}")
                raise RuntimeError(f"Video processing failed: {error_msg}")

    def _merge_video_audio(self, video_file: Path, audio_file: Path, output_file: Path):
        """Merge processed video with mixed audio"""
        try:
            # Debug: Check if video file has video stream
            print(f"Merging video: {video_file} (exists: {video_file.exists()})")
            print(f"Merging audio: {audio_file} (exists: {audio_file.exists()})")

            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_file),
                "-i", str(audio_file),
                "-c:v", "copy",  # Copy video (already encoded)
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",  # End when shortest stream ends
                str(output_file)
            ]

            print(f"Merge command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)

            if result.stderr:
                print(f"FFmpeg merge stderr: {result.stderr}")

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if hasattr(e.stderr, 'decode') else str(e.stderr)
            print(f"MERGE ERROR: {error_msg}")
            raise RuntimeError(f"Video/audio merge failed: {error_msg}")
