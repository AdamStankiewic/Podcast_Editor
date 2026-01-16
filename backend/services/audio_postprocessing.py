"""
Audio Post-Processing Service
Applies studio-quality enhancements to TTS-generated audio:
1. Pre-conversion to mono 48kHz
2. Noise cleanup (DeepFilterNet - optional)
3. Studio chain (EQ + compression + limiter)
4. LUFS normalization (-16 LUFS for podcasts)
"""
import subprocess
import shutil
from pathlib import Path
from typing import Optional


class AudioPostProcessingService:
    """Enhances TTS audio with studio-quality processing"""

    def __init__(
        self,
        enable_denoise: bool = True,
        enable_studio_chain: bool = True,
        target_lufs: float = -16.0,
        true_peak_db: float = -1.0
    ):
        self.enable_denoise = enable_denoise
        self.enable_studio_chain = enable_studio_chain
        self.target_lufs = target_lufs
        self.true_peak_db = true_peak_db

        # Check if DeepFilterNet is available
        self.deepfilter_available = self._check_deepfilter()

    def _check_deepfilter(self) -> bool:
        """Check if deep-filter command is available"""
        try:
            result = subprocess.run(
                ["deep-filter", "--help"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def process_audio(
        self,
        input_wav: Path,
        output_wav: Path,
        progress_callback: Optional[callable] = None
    ) -> Path:
        """
        Apply full studio processing chain to audio

        Args:
            input_wav: TTS-generated WAV file
            output_wav: Output path for processed audio
            progress_callback: Optional callback(current, total, message)

        Returns:
            Path to processed audio file
        """
        temp_dir = output_wav.parent / f"_postprocessing_{output_wav.stem}"
        temp_dir.mkdir(exist_ok=True, parents=True)

        try:
            # Step 1: Pre-conversion to mono 48kHz s16
            if progress_callback:
                progress_callback(1, 4, "Converting to studio format (mono 48kHz)...")

            tmp_48k_mono = temp_dir / "tmp_48k_mono.wav"
            self._pre_convert(input_wav, tmp_48k_mono)

            # Step 2: Noise cleanup (DeepFilterNet - optional)
            if self.enable_denoise and self.deepfilter_available:
                if progress_callback:
                    progress_callback(2, 4, "Applying noise reduction (DeepFilterNet)...")

                tmp_clean = temp_dir / "tmp_clean.wav"
                self._denoise(tmp_48k_mono, tmp_clean, temp_dir)
            else:
                if self.enable_denoise and not self.deepfilter_available:
                    print("Warning: DeepFilterNet not available, skipping noise reduction")
                tmp_clean = tmp_48k_mono

            # Step 3: Studio chain (EQ + compression + limiter)
            if progress_callback:
                progress_callback(3, 4, "Applying studio processing (EQ, compression)...")

            tmp_studio = temp_dir / "tmp_studio.wav"
            if self.enable_studio_chain:
                self._apply_studio_chain(tmp_clean, tmp_studio)
            else:
                shutil.copy2(tmp_clean, tmp_studio)

            # Step 4: LUFS normalization
            if progress_callback:
                progress_callback(4, 4, f"Normalizing to {self.target_lufs} LUFS...")

            self._normalize_lufs(tmp_studio, output_wav)

            # Cleanup
            shutil.rmtree(temp_dir)

            print(f"✓ Audio post-processing complete: {output_wav}")
            return output_wav

        except Exception as e:
            # Cleanup on error
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise RuntimeError(f"Audio post-processing failed: {e}")

    def _pre_convert(self, input_wav: Path, output_wav: Path):
        """Convert audio to mono 48kHz s16 for processing"""
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(input_wav),
                "-ac", "1",  # Mono
                "-ar", "48000",  # 48kHz
                "-sample_fmt", "s16",  # 16-bit signed
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Pre-conversion failed: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _denoise(self, input_wav: Path, output_wav: Path, temp_dir: Path):
        """Apply DeepFilterNet noise reduction"""
        try:
            # DeepFilterNet outputs to a subdirectory
            df_output_dir = temp_dir / "tmp_df"
            df_output_dir.mkdir(exist_ok=True)

            subprocess.run([
                "deep-filter",
                "-D",  # Post-filter (best quality)
                "-o", str(df_output_dir),
                str(input_wav)
            ], check=True, capture_output=True)

            # Find the output file (DeepFilterNet keeps original basename)
            expected_output = df_output_dir / input_wav.name
            if expected_output.exists():
                shutil.move(str(expected_output), str(output_wav))
            else:
                # Fallback: find first WAV in output dir
                wav_files = list(df_output_dir.glob("*.wav"))
                if wav_files:
                    shutil.move(str(wav_files[0]), str(output_wav))
                else:
                    raise RuntimeError("DeepFilterNet did not produce output file")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Denoising failed: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _apply_studio_chain(self, input_wav: Path, output_wav: Path):
        """
        Apply studio processing chain:
        - High-pass filter (80 Hz) - remove rumble
        - EQ adjustments (reduce 220Hz, boost 3.5kHz and 9kHz for clarity)
        - Compression (smooth dynamics)
        - Limiter (prevent clipping)
        """
        try:
            # Build filter chain
            filter_chain = ",".join([
                "highpass=f=80",  # Remove low rumble
                "equalizer=f=220:t=q:w=1.0:g=-3",  # Reduce muddiness
                "equalizer=f=3500:t=q:w=1.0:g=2",  # Add presence
                "equalizer=f=9000:t=q:w=1.0:g=2",  # Add air/brightness
                "acompressor=threshold=-20dB:ratio=3:attack=10:release=80:makeup=4",  # Smooth dynamics
                "alimiter=limit=0.891"  # Prevent clipping (-1 dB)
            ])

            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(input_wav),
                "-af", filter_chain,
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Studio chain failed: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _normalize_lufs(self, input_wav: Path, output_wav: Path):
        """
        Normalize audio to target LUFS (loudness standard)
        -16 LUFS is standard for podcasts/YouTube
        """
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(input_wav),
                "-af", f"loudnorm=I={self.target_lufs}:TP={self.true_peak_db}:LRA=11",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"LUFS normalization failed: {e.stderr.decode() if e.stderr else 'unknown'}")


# Singleton instance
_audio_postprocessing_service = None


def get_audio_postprocessing(
    enable_denoise: bool = True,
    enable_studio_chain: bool = True,
    target_lufs: float = -16.0
) -> AudioPostProcessingService:
    """Get or create audio post-processing service instance"""
    global _audio_postprocessing_service
    if _audio_postprocessing_service is None:
        _audio_postprocessing_service = AudioPostProcessingService(
            enable_denoise=enable_denoise,
            enable_studio_chain=enable_studio_chain,
            target_lufs=target_lufs
        )
    return _audio_postprocessing_service
