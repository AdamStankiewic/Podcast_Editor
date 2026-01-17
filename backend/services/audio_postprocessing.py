"""
Audio Post-Processing Service
Applies studio-quality enhancements to TTS-generated audio:
1. Pre-conversion to mono 48kHz
2. AI Enhancement (Resemble Enhance - optional, GPU accelerated)
3. Noise cleanup (DeepFilterNet - optional, fallback if Resemble not available)
4. Studio chain (EQ + compression + limiter)
5. LUFS normalization (-16 LUFS for podcasts)
"""
import subprocess
import shutil
import os
from pathlib import Path
from typing import Optional


class AudioPostProcessingService:
    """Enhances TTS audio with studio-quality processing"""

    def __init__(
        self,
        enable_ai_enhance: bool = True,
        enable_denoise: bool = True,
        enable_studio_chain: bool = True,
        target_lufs: float = -16.0,
        true_peak_db: float = -1.0
    ):
        self.enable_ai_enhance = enable_ai_enhance
        self.enable_denoise = enable_denoise
        self.enable_studio_chain = enable_studio_chain
        self.target_lufs = target_lufs
        self.true_peak_db = true_peak_db

        # Check AI enhancement tools availability
        self.resemble_available = self._check_resemble_enhance()
        self.deepfilter_available = self._check_deepfilter()

        # Log available tools
        if self.resemble_available:
            print("✓ Resemble Enhance available (AI voice enhancement with GPU)")
        elif self.deepfilter_available:
            print("✓ DeepFilterNet available (noise reduction)")
        else:
            print("⚠ No AI enhancement tools available, using FFmpeg filters only")

    def _check_resemble_enhance(self) -> bool:
        """Check if Resemble Enhance is available"""
        try:
            import torch
            from resemble_enhance.enhancer.inference import enhance
            # Check if CUDA is available for GPU acceleration
            if torch.cuda.is_available():
                print(f"✓ CUDA available: {torch.cuda.get_device_name(0)}")
            return True
        except ImportError:
            return False

    def _check_deepfilter(self) -> bool:
        """Check if DeepFilterNet Python module is available"""
        try:
            import df  # DeepFilterNet module
            return True
        except ImportError:
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
            current_step = 0
            total_steps = 5

            # Step 1: Pre-conversion to mono 48kHz s16
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Converting to studio format (mono 48kHz)...")

            tmp_48k_mono = temp_dir / "tmp_48k_mono.wav"
            self._pre_convert(input_wav, tmp_48k_mono)

            # Step 2: AI Enhancement (Resemble Enhance - priority over DeepFilterNet)
            current_audio = tmp_48k_mono

            if self.enable_ai_enhance and self.resemble_available:
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps, "Applying AI voice enhancement (Resemble Enhance)...")

                tmp_enhanced = temp_dir / "tmp_enhanced.wav"
                self._apply_resemble_enhance(current_audio, tmp_enhanced)
                current_audio = tmp_enhanced
                print("✓ AI enhancement applied (Resemble Enhance)")

            # Step 3: Fallback noise reduction (DeepFilterNet - only if Resemble not used)
            elif self.enable_denoise and self.deepfilter_available:
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_steps, "Applying noise reduction (DeepFilterNet)...")

                tmp_clean = temp_dir / "tmp_clean.wav"
                self._denoise(current_audio, tmp_clean, temp_dir)
                current_audio = tmp_clean
                print("✓ Noise reduction applied (DeepFilterNet)")
            else:
                current_step += 1  # Skip step but keep numbering
                if self.enable_ai_enhance or self.enable_denoise:
                    print("⚠ No AI enhancement tools available, skipping to FFmpeg processing")

            # Step 4: Studio chain (EQ + compression + limiter)
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, "Applying studio processing (EQ, compression)...")

            tmp_studio = temp_dir / "tmp_studio.wav"
            if self.enable_studio_chain:
                self._apply_studio_chain(current_audio, tmp_studio)
            else:
                shutil.copy2(current_audio, tmp_studio)

            # Step 5: LUFS normalization
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, f"Normalizing to {self.target_lufs} LUFS...")

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

    def _apply_resemble_enhance(self, input_wav: Path, output_wav: Path):
        """
        Apply Resemble Enhance AI voice enhancement
        This is the BEST option for TTS - makes synthetic voice sound natural
        """
        try:
            import torch
            from resemble_enhance.enhancer.inference import enhance

            # Set device (CUDA if available, else CPU)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Using device for AI enhancement: {device}")

            # Run enhancement
            # solver: Diffusion solver (midpoint is good balance of quality/speed)
            # nfe: Number of function evaluations (higher = better quality but slower)
            # tau: Denoising strength (0.5 = balanced)
            enhance(
                model_path=None,  # Auto-download model
                input_path=str(input_wav),
                output_path=str(output_wav),
                solver="midpoint",
                nfe=64,  # Good balance (32=fast, 64=balanced, 128=best quality)
                tau=0.5,  # Denoising strength
                denoising=True,
                device=device
            )

            print(f"✓ Resemble Enhance completed: {output_wav}")

        except Exception as e:
            raise RuntimeError(f"Resemble Enhance failed: {e}")

    def _denoise(self, input_wav: Path, output_wav: Path, temp_dir: Path):
        """Apply DeepFilterNet noise reduction using Python API"""
        try:
            import torch
            import torchaudio
            from df import enhance, init_df

            print(f"Loading DeepFilterNet model...")

            # Initialize DeepFilterNet model
            model, df_state, _ = init_df()

            # Try GPU first, fallback to CPU if OOM error
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = model.to(device)

            print(f"DeepFilterNet using device: {device}")
            if torch.cuda.is_available():
                print(f"GPU: {torch.cuda.get_device_name(0)}, Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

            # Load audio
            audio, sr = torchaudio.load(str(input_wav))

            # Convert to mono if stereo (DeepFilterNet works better with mono)
            if audio.shape[0] > 1:
                audio = torch.mean(audio, dim=0, keepdim=True)

            print(f"Processing audio: {audio.shape}, sample rate: {sr}")

            try:
                audio = audio.to(device)

                # Enhance audio
                enhanced = enhance(model, df_state, audio, sr)
                enhanced = enhanced.cpu()

                print(f"✓ DeepFilterNet denoising complete (GPU)")

            except torch.cuda.OutOfMemoryError:
                print(f"⚠ GPU out of memory, falling back to CPU...")

                # Clear GPU memory
                torch.cuda.empty_cache()

                # Retry on CPU
                device = torch.device("cpu")
                model = model.to(device)
                audio = audio.cpu()

                enhanced = enhance(model, df_state, audio, sr)

                print(f"✓ DeepFilterNet denoising complete (CPU fallback)")

            # Save enhanced audio
            torchaudio.save(str(output_wav), enhanced, sr)

        except Exception as e:
            raise RuntimeError(f"DeepFilterNet denoising failed: {e}")

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
    enable_ai_enhance: bool = True,
    enable_denoise: bool = True,
    enable_studio_chain: bool = True,
    target_lufs: float = -16.0
) -> AudioPostProcessingService:
    """Get or create audio post-processing service instance"""
    global _audio_postprocessing_service
    if _audio_postprocessing_service is None:
        _audio_postprocessing_service = AudioPostProcessingService(
            enable_ai_enhance=enable_ai_enhance,
            enable_denoise=enable_denoise,
            enable_studio_chain=enable_studio_chain,
            target_lufs=target_lufs
        )
    return _audio_postprocessing_service
