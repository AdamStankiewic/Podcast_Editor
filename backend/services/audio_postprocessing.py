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
            import torchaudio
            from resemble_enhance.enhancer.inference import enhance

            # Set device (CUDA if available, else CPU)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"Using device for AI enhancement: {device}")

            # Load audio
            dwav, sr = torchaudio.load(str(input_wav))

            # Convert to mono if needed (resemble-enhance works best with mono)
            if dwav.shape[0] > 1:
                dwav = torch.mean(dwav, dim=0, keepdim=True)

            print(f"Processing audio: {dwav.shape}, sample rate: {sr}")

            # Run enhancement
            # Parameters:
            # - nfe: Number of function evaluations (higher = better quality, 128 = max)
            # - solver: ODE solver ('midpoint' is good balance of quality/speed)
            # - lambd: 0.9 for denoising, 0.1 for enhancement only
            # - tau: Prior temperature (0.5 = balanced)
            enhanced_wav, new_sr = enhance(
                dwav,
                sr,
                device,
                nfe=128,  # Maximum quality (1-128)
                solver="midpoint",  # midpoint/rk4/euler
                lambd=0.9,  # Enable denoising
                tau=0.5  # Prior temperature
            )

            # Save enhanced audio
            torchaudio.save(str(output_wav), enhanced_wav.cpu(), new_sr)

            print(f"✓ Resemble Enhance completed: {output_wav}")

        except Exception as e:
            raise RuntimeError(f"Resemble Enhance failed: {e}")

    def _denoise(self, input_wav: Path, output_wav: Path, temp_dir: Path):
        """Apply DeepFilterNet noise reduction using Python API with chunk-based processing"""
        try:
            import torch
            import torchaudio
            from df import enhance, init_df

            print(f"Loading DeepFilterNet model...")

            # Initialize DeepFilterNet model on GPU
            model, df_state, _ = init_df()

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

            # Calculate chunk size (5 minutes at sample rate to avoid 32-bit indexing limit)
            # 5 minutes = 300 seconds * 48000 Hz = 14,400,000 samples (well under 2^31 limit)
            chunk_duration_sec = 300  # 5 minutes
            overlap_sec = 2  # 2 seconds overlap between chunks for smooth transitions

            chunk_size = chunk_duration_sec * sr
            overlap_size = overlap_sec * sr
            total_samples = audio.shape[1]

            # Check if we need chunking (audio longer than 10 minutes)
            needs_chunking = total_samples > (chunk_size * 2)

            if needs_chunking:
                print(f"⚠ Audio is large ({total_samples / sr / 60:.1f} min), using chunk-based processing to avoid GPU limits...")
                print(f"Splitting into {chunk_size / sr / 60:.0f}-minute chunks with {overlap_sec}s overlap for smooth transitions...")

                # Process in chunks with overlap
                enhanced_chunks = []
                num_chunks = (total_samples + chunk_size - 1) // chunk_size  # Ceiling division

                for i in range(num_chunks):
                    # Add overlap: include extra samples from previous/next chunk
                    start_idx = max(0, i * chunk_size - overlap_size)
                    end_idx = min((i + 1) * chunk_size + overlap_size, total_samples)

                    chunk = audio[:, start_idx:end_idx]

                    print(f"Processing chunk {i+1}/{num_chunks} ({chunk.shape[1] / sr / 60:.1f} min)...")

                    try:
                        # Enhance chunk (DeepFilterNet handles GPU internally)
                        enhanced_chunk = enhance(model, df_state, chunk, sr)

                        # Store with metadata about overlap regions
                        enhanced_chunks.append({
                            'audio': enhanced_chunk,
                            'start_idx': start_idx,
                            'end_idx': end_idx,
                            'chunk_idx': i
                        })
                    except Exception as e:
                        print(f"⚠ Error processing chunk {i+1}: {e}")
                        raise

                # Concatenate chunks with crossfading in overlap regions
                print(f"Concatenating {len(enhanced_chunks)} chunks with crossfading...")

                # Initialize output tensor
                enhanced = torch.zeros((1, total_samples))

                for i, chunk_data in enumerate(enhanced_chunks):
                    chunk_audio = chunk_data['audio']
                    start_idx = chunk_data['start_idx']
                    end_idx = chunk_data['end_idx']

                    # Calculate actual chunk boundaries (without overlap for final output)
                    chunk_start = i * chunk_size
                    chunk_end = min((i + 1) * chunk_size, total_samples)

                    # Calculate position within the enhanced chunk
                    offset_start = chunk_start - start_idx
                    offset_end = offset_start + (chunk_end - chunk_start)

                    # Extract the core part (without overlap regions)
                    core = chunk_audio[:, offset_start:offset_end]

                    if i == 0:
                        # First chunk: no fade-in
                        enhanced[:, chunk_start:chunk_end] = core
                    elif i == len(enhanced_chunks) - 1:
                        # Last chunk: no fade-out, but crossfade with previous
                        # Crossfade at the beginning
                        fade_samples = min(overlap_size, core.shape[1])
                        fade_in = torch.linspace(0, 1, fade_samples).unsqueeze(0)
                        fade_out = torch.linspace(1, 0, fade_samples).unsqueeze(0)

                        # Blend overlap region
                        enhanced[:, chunk_start:chunk_start + fade_samples] = (
                            enhanced[:, chunk_start:chunk_start + fade_samples] * fade_out +
                            core[:, :fade_samples] * fade_in
                        )
                        # Copy rest
                        if fade_samples < core.shape[1]:
                            enhanced[:, chunk_start + fade_samples:chunk_end] = core[:, fade_samples:]
                    else:
                        # Middle chunks: crossfade at beginning
                        fade_samples = min(overlap_size, core.shape[1])
                        fade_in = torch.linspace(0, 1, fade_samples).unsqueeze(0)
                        fade_out = torch.linspace(1, 0, fade_samples).unsqueeze(0)

                        # Blend overlap region
                        enhanced[:, chunk_start:chunk_start + fade_samples] = (
                            enhanced[:, chunk_start:chunk_start + fade_samples] * fade_out +
                            core[:, :fade_samples] * fade_in
                        )
                        # Copy rest
                        if fade_samples < core.shape[1]:
                            enhanced[:, chunk_start + fade_samples:chunk_end] = core[:, fade_samples:]

                print(f"✓ DeepFilterNet denoising complete (GPU, chunk-based processing with crossfading)")

            else:
                # Process entire audio at once (faster for smaller files)
                print(f"Audio size is OK ({total_samples / sr / 60:.1f} min), processing in one pass...")

                # IMPORTANT: DeepFilterNet's enhance() expects audio on CPU
                # It will handle moving to GPU internally
                enhanced = enhance(model, df_state, audio, sr)

                print(f"✓ DeepFilterNet denoising complete (GPU)")

            # Save enhanced audio
            torchaudio.save(str(output_wav), enhanced, sr)

        except Exception as e:
            raise RuntimeError(f"DeepFilterNet denoising failed: {e}")

    def _apply_studio_chain(self, input_wav: Path, output_wav: Path):
        """
        Apply studio processing chain:
        - High-pass filter (80 Hz) - remove rumble
        - EQ adjustments for warmth and clarity
        - De-esser (reduce harsh sibilance)
        - Compression (smooth dynamics, add punch)
        - Limiter (prevent clipping)
        """
        try:
            # Build filter chain - more aggressive for "studyjne brzmienie"
            filter_chain = ",".join([
                "highpass=f=80",  # Remove low rumble
                "equalizer=f=150:t=q:w=1.5:g=2",  # Add warmth/body
                "equalizer=f=250:t=q:w=1.0:g=-2",  # Reduce muddiness
                "equalizer=f=2500:t=q:w=1.5:g=4",  # Add clarity/presence (wyrazistość)
                "equalizer=f=4500:t=q:w=1.0:g=3",  # Add intelligibility
                "equalizer=f=7000:t=q:w=2.0:g=-4",  # De-ess: reduce harsh sibilance (s/sz sounds)
                "equalizer=f=10000:t=q:w=2.0:g=2",  # Add air/brightness
                "acompressor=threshold=-24dB:ratio=4:attack=5:release=50:makeup=6",  # More punch
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
