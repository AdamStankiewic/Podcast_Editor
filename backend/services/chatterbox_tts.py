"""
Chatterbox TTS Provider

Uses Resemble AI's Chatterbox Multilingual for high-quality TTS with:
- Voice cloning (zero-shot)
- Emotion/exaggeration control
- 23 language support
- Optimized for podcast narration
"""
import os
import re
import gc
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, List

import torch
import torchaudio

from backend.services.tts_provider import (
    TTSProvider,
    TTSProviderType,
    TTSConfig,
    TTSResult
)


class ChatterboxTTSProvider(TTSProvider):
    """
    Chatterbox Multilingual TTS Provider

    Features:
    - Voice cloning from reference audio
    - Emotion control via exaggeration parameter
    - Support for 23 languages including Polish, French, English
    - Paralinguistic tags: [laugh], [chuckle], [cough], etc.
    """

    provider_type = TTSProviderType.CHATTERBOX

    # Supported languages with their codes
    SUPPORTED_LANGUAGES = {
        "ar": "Arabic",
        "da": "Danish",
        "de": "German",
        "el": "Greek",
        "en": "English",
        "es": "Spanish",
        "fi": "Finnish",
        "fr": "French",
        "he": "Hebrew",
        "hi": "Hindi",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "ms": "Malay",
        "nl": "Dutch",
        "no": "Norwegian",
        "pl": "Polish",
        "pt": "Portuguese",
        "ru": "Russian",
        "sv": "Swedish",
        "sw": "Swahili",
        "tr": "Turkish",
        "zh": "Chinese"
    }

    def __init__(
        self,
        device: str = "cuda",
        model_variant: str = "multilingual",  # "multilingual", "turbo", "standard"
        reference_audio_path: Optional[str] = None
    ):
        """
        Initialize Chatterbox TTS Provider

        Args:
            device: Device to use ("cuda" or "cpu")
            model_variant: Which Chatterbox model to use
            reference_audio_path: Path to reference audio for voice cloning
        """
        self.device = device if torch.cuda.is_available() else "cpu"
        self.model_variant = model_variant
        self.reference_audio_path = reference_audio_path
        self.model = None
        self._model_loaded = False

        # Chunking configuration (for long texts)
        self.max_chars = 500  # Chatterbox works best with shorter chunks
        self.chunk_delay_sec = 0.3
        self.min_valid_wav_bytes = 10_000

        print(f"ChatterboxTTSProvider initialized (device={self.device}, variant={model_variant})")

    def _load_model(self):
        """Lazy load the model on first use"""
        if self._model_loaded:
            return

        print(f"Loading Chatterbox {self.model_variant} model...")

        if self.model_variant == "multilingual":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            self.model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        elif self.model_variant == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            self.model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        else:  # standard
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=self.device)

        self._model_loaded = True
        print(f"Chatterbox model loaded successfully (sample_rate={self.model.sr})")

    def generate_audio(
        self,
        text: str,
        output_path: Path,
        config: TTSConfig,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> TTSResult:
        """
        Generate audio from text using Chatterbox

        Args:
            text: Plain text to synthesize
            output_path: Path for output WAV file
            config: TTS configuration
            progress_callback: Optional callback(current, total, message)

        Returns:
            TTSResult with audio path and metadata
        """
        # Ensure model is loaded
        self._load_model()

        # Create temp directory for chunks
        temp_base = os.getenv("TEMP_PATH", str(output_path.parent))
        temp_dir = Path(temp_base) / f"_temp_chatterbox_{output_path.stem}"
        temp_dir.mkdir(exist_ok=True, parents=True)

        try:
            # Step 1: Normalize and split text
            if progress_callback:
                progress_callback(1, 4, "Preparing text chunks...")

            text = self._normalize_text(text)
            chunks = self._split_into_chunks(text, self.max_chars)

            print(f"Split into {len(chunks)} chunks for Chatterbox")

            # Get reference audio path
            ref_audio = self._get_reference_audio(config)

            # Step 2: Generate audio chunks
            if progress_callback:
                progress_callback(2, 4, f"Generating {len(chunks)} audio chunks...")

            all_wavs = []

            for i, chunk in enumerate(chunks, 1):
                if progress_callback:
                    progress_callback(2, 4, f"Generating chunk {i}/{len(chunks)}...")

                # Generate audio for chunk
                wav = self._synthesize_chunk(
                    chunk,
                    config=config,
                    ref_audio=ref_audio,
                    chunk_index=i,
                    total_chunks=len(chunks)
                )

                # Save chunk to temp file
                part_wav = temp_dir / f"part_{i:03d}.wav"
                torchaudio.save(str(part_wav), wav, self.model.sr)
                all_wavs.append(part_wav)

                # Small delay between chunks
                if i < len(chunks):
                    time.sleep(self.chunk_delay_sec)

            # Step 3: Merge chunks
            if progress_callback:
                progress_callback(3, 4, "Merging audio chunks...")

            raw_wav = temp_dir / f"{output_path.stem}_raw.wav"
            self._concat_wavs(temp_dir, raw_wav)

            # Step 4: Loudness normalization
            if progress_callback:
                progress_callback(4, 4, "Normalizing loudness...")

            self._normalize_loudness(raw_wav, output_path)

            # Calculate duration
            duration = self._get_audio_duration(output_path)

            # Cleanup
            self._cleanup_temp_dir(temp_dir)

            return TTSResult(
                audio_path=output_path,
                duration_seconds=duration,
                provider=self.provider_type,
                metadata={
                    "chunks": len(chunks),
                    "model_variant": self.model_variant,
                    "exaggeration": config.exaggeration,
                    "cfg_weight": config.cfg_weight,
                    "language": config.target_language,
                    "voice_cloning": ref_audio is not None
                }
            )

        except Exception as e:
            # Cleanup on error
            self._cleanup_temp_dir(temp_dir)
            raise RuntimeError(f"Chatterbox TTS generation failed: {e}")

    def _synthesize_chunk(
        self,
        text: str,
        config: TTSConfig,
        ref_audio: Optional[str],
        chunk_index: int,
        total_chunks: int
    ) -> torch.Tensor:
        """Synthesize a single text chunk"""
        try:
            # Prepare generation kwargs
            gen_kwargs = {
                "exaggeration": config.exaggeration,
                "cfg_weight": config.cfg_weight
            }

            # Add reference audio if available (voice cloning)
            if ref_audio and Path(ref_audio).exists():
                gen_kwargs["audio_prompt_path"] = ref_audio

            # Add language for multilingual model
            if self.model_variant == "multilingual":
                gen_kwargs["language_id"] = config.target_language

            # Generate audio
            wav = self.model.generate(text, **gen_kwargs)

            print(f"Chatterbox chunk {chunk_index}/{total_chunks}")
            return wav

        except Exception as e:
            raise RuntimeError(f"Failed to synthesize chunk {chunk_index}: {e}")

    def _get_reference_audio(self, config: TTSConfig) -> Optional[str]:
        """Get reference audio path for voice cloning"""
        # Priority: config.voice (if it's a path) > self.reference_audio_path > env var
        if config.voice and Path(config.voice).exists():
            return config.voice

        if self.reference_audio_path and Path(self.reference_audio_path).exists():
            return self.reference_audio_path

        env_ref = os.getenv("CHATTERBOX_REFERENCE_AUDIO")
        if env_ref and Path(env_ref).exists():
            return env_ref

        # No reference audio - will use default voice
        return None

    def _normalize_text(self, text: str) -> str:
        """Normalize text whitespace"""
        text = text.replace("\r\n", "\n").strip()
        text = re.sub(r"[ \t]+", " ", text)
        return text

    def _split_into_chunks(self, text: str, max_len: int) -> List[str]:
        """Split text into chunks respecting sentence boundaries"""
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks = []
        current = ""
        sent_split = re.compile(r"(?<=[\.\!\?])\s+")

        def flush():
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
                current = ""

        for p in paragraphs:
            if len(p) <= max_len:
                if len(current) + len(p) + 2 <= max_len:
                    current += p + " "
                else:
                    flush()
                    current = p + " "
            else:
                sentences = sent_split.split(p)
                for s in sentences:
                    s = s.strip()
                    if not s:
                        continue
                    if len(s) > max_len:
                        # Very long sentence - split by commas or force split
                        for part in self._split_long_sentence(s, max_len):
                            if len(current) + len(part) + 1 <= max_len:
                                current += part + " "
                            else:
                                flush()
                                current = part + " "
                    else:
                        if len(current) + len(s) + 1 <= max_len:
                            current += s + " "
                        else:
                            flush()
                            current = s + " "

        flush()
        return chunks

    def _split_long_sentence(self, sentence: str, max_len: int) -> List[str]:
        """Split a very long sentence by commas or force split"""
        # Try splitting by commas first
        parts = sentence.split(", ")
        if len(parts) > 1:
            result = []
            current = ""
            for part in parts:
                if len(current) + len(part) + 2 <= max_len:
                    current += part + ", "
                else:
                    if current:
                        result.append(current.rstrip(", "))
                    current = part + ", "
            if current:
                result.append(current.rstrip(", "))
            return result

        # Force split by character count
        return [sentence[i:i+max_len] for i in range(0, len(sentence), max_len)]

    def _concat_wavs(self, temp_dir: Path, output_wav: Path):
        """Concatenate WAV files using ffmpeg"""
        parts = sorted(temp_dir.glob("part_*.wav"))
        if not parts:
            raise RuntimeError("No part_*.wav files to concatenate")

        # Create concat file list
        files_txt = temp_dir / "files.txt"
        with files_txt.open("w", encoding="ascii") as f:
            for p in parts:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(files_txt),
                # Apply noise gate to remove artifacts
                "-af", "agate=threshold=-40dB:ratio=2:attack=5:release=50",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg concat failed: {e.stderr.decode() if e.stderr else 'unknown'}")
        finally:
            if files_txt.exists():
                files_txt.unlink()

    def _normalize_loudness(self, input_wav: Path, output_wav: Path):
        """Apply loudness normalization using ffmpeg (podcast standard: -19 LUFS)"""
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(input_wav),
                "-af", "loudnorm=I=-19:TP=-2:LRA=16",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Loudness normalization failed: {e.stderr.decode() if e.stderr else 'unknown'}")

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration in seconds"""
        try:
            result = subprocess.run([
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ], capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except Exception:
            # Fallback: estimate from file size
            return audio_path.stat().st_size / (48000 * 2 * 2)

    def _cleanup_temp_dir(self, temp_dir: Path):
        """Cleanup temp directory with retry logic"""
        if not temp_dir.exists():
            return

        for retry in range(3):
            try:
                shutil.rmtree(temp_dir)
                break
            except PermissionError:
                if retry < 2:
                    time.sleep(0.5)
                else:
                    print(f"Warning: Could not delete temp dir {temp_dir}")

    def supports_voice_cloning(self) -> bool:
        """Chatterbox supports zero-shot voice cloning"""
        return True

    def set_reference_audio(self, audio_path: Path) -> None:
        """Set reference audio for voice cloning"""
        if not audio_path.exists():
            raise FileNotFoundError(f"Reference audio not found: {audio_path}")
        self.reference_audio_path = str(audio_path)
        print(f"Reference audio set: {audio_path}")

    def get_supported_languages(self) -> list:
        """Get list of supported language codes"""
        return list(self.SUPPORTED_LANGUAGES.keys())

    def validate_config(self, config: TTSConfig) -> tuple[bool, str]:
        """Validate configuration"""
        errors = []

        if config.target_language not in self.SUPPORTED_LANGUAGES:
            errors.append(f"Unsupported language: {config.target_language}")

        if not 0.0 <= config.exaggeration <= 1.0:
            errors.append(f"Exaggeration must be 0.0-1.0, got {config.exaggeration}")

        if not 0.0 <= config.cfg_weight <= 1.0:
            errors.append(f"cfg_weight must be 0.0-1.0, got {config.cfg_weight}")

        if errors:
            return False, "; ".join(errors)

        return True, ""

    def unload_model(self):
        """Unload model to free GPU memory"""
        if self.model is not None:
            del self.model
            self.model = None
            self._model_loaded = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("Chatterbox model unloaded")
