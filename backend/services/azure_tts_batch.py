"""
Azure TTS Batch Service - Adapted from original script
Generates long-form audio using Azure Neural TTS with chunking and merging
"""
import os
import re
import time
import gc
import shutil
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Callable
import azure.cognitiveservices.speech as speechsdk


class AzureTTSBatchService:
    """Azure TTS service for long-form audio generation"""

    def __init__(
        self,
        speech_key: str,
        speech_region: str,
        voice: str = "en-GB-Ollie:DragonHDLatestNeural",
        rate: str = "-8%",
        pitch: str = "0%"
    ):
        self.speech_key = speech_key
        self.speech_region = speech_region
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

        # Azure configuration
        self.max_chars = 3000  # Chunk size for SSML
        self.max_retries = 5
        self.retry_backoff_sec = 10  # Increased from 5 to 10 seconds
        self.min_valid_wav_bytes = 200_000
        self.chunk_delay_sec = 0.5  # Delay between chunks to avoid overwhelming Azure

        # Initialize speech config
        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.speech_key,
            region=self.speech_region
        )

        # Set longer timeouts for Azure SDK (helps with slow synthesis)
        # Connection timeout: 30 seconds
        # Synthesis timeout: 120 seconds (2 minutes per chunk)
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
            "30000"  # 30 seconds for initial connection
        )
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
            "120000"  # 120 seconds for synthesis timeout
        )

    def generate_audio(
        self,
        text: str,
        output_wav: Path,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Path:
        """
        Generate audio from text/SSML

        Args:
            text: Plain text or SSML string
            output_wav: Path to output WAV file
            progress_callback: Optional callback(current, total, message)

        Returns:
            Path to generated WAV file
        """
        # Create temp directory for chunks
        # Use RAM Disk if configured for faster I/O
        temp_base = os.getenv("TEMP_PATH", str(output_wav.parent))
        temp_dir = Path(temp_base) / f"_temp_{output_wav.stem}"
        temp_dir.mkdir(exist_ok=True, parents=True)

        try:
            # Step 1: Normalize and split text
            if progress_callback:
                progress_callback(1, 4, "Preparing text chunks...")

            text = self._normalize_text(text)
            chunks = self._split_into_chunks(text, self.max_chars)

            print(f"Split into {len(chunks)} chunks")

            # Step 2: Generate audio chunks
            if progress_callback:
                progress_callback(2, 4, f"Generating {len(chunks)} audio chunks...")

            for i, chunk in enumerate(chunks, 1):
                part_wav = temp_dir / f"part_{i:03d}.wav"

                # Skip if already exists
                if self._wav_looks_ok(part_wav):
                    print(f"↷ Skip (exists): {part_wav.name}")
                    continue

                ssml = self._build_ssml(chunk)

                if progress_callback:
                    progress_callback(2, 4, f"Generating chunk {i}/{len(chunks)}...")

                self._synthesize_chunk(ssml, part_wav, chunk_index=i, total_chunks=len(chunks))

                # Add small delay between chunks to avoid overwhelming Azure API
                if i < len(chunks):  # Don't delay after last chunk
                    time.sleep(self.chunk_delay_sec)

                # Delay between requests to avoid throttling
                if i < len(chunks):
                    time.sleep(2)

            # Step 3: Merge chunks
            if progress_callback:
                progress_callback(3, 4, "Merging audio chunks...")

            # Use temp directory for intermediate raw file
            raw_wav = temp_dir / f"{output_wav.stem}_raw.wav"
            self._concat_wavs(temp_dir, raw_wav)

            # Step 4: Loudness normalization
            if progress_callback:
                progress_callback(4, 4, "Normalizing loudness...")

            self._normalize_loudness(raw_wav, output_wav)

            # Cleanup temp files
            # Note: Windows may hold file handles, use retry logic
            # Delete raw file first (if separate from output)
            if raw_wav.exists() and raw_wav != output_wav:
                try:
                    raw_wav.unlink()
                except Exception:
                    pass  # Ignore cleanup errors

            # Retry temp directory deletion (Windows file handle issue)
            for retry in range(3):
                try:
                    shutil.rmtree(temp_dir)
                    break
                except PermissionError:
                    if retry < 2:
                        time.sleep(0.5)  # Wait for file handles to close
                    else:
                        print(f"Warning: Could not delete temp dir {temp_dir} (files may be in use)")

            return output_wav

        except Exception as e:
            # Cleanup on error (best effort)
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass  # Ignore cleanup errors on failure
            raise RuntimeError(f"Azure TTS generation failed: {e}")

    def _normalize_text(self, text: str) -> str:
        """Normalize text whitespace"""
        text = text.replace("\r\n", "\n").strip()
        text = re.sub(r"[ \t]+", " ", text)
        return text

    def _split_into_chunks(self, text: str, max_len: int) -> list:
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
                    current += p + "\n\n"
                else:
                    flush()
                    current = p + "\n\n"
            else:
                sentences = sent_split.split(p)
                for s in sentences:
                    s = s.strip()
                    if not s:
                        continue
                    if len(s) > max_len:
                        for i in range(0, len(s), max_len):
                            part = s[i:i+max_len]
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
                current += "\n\n"

        flush()
        return chunks

    def _build_ssml(self, chunk: str) -> str:
        """
        Build SSML from text chunk
        Note: If chunk already contains SSML tags (like <sub>, <phoneme>),
        they will be preserved inside the prosody element
        """
        # Don't escape if already SSML
        if "<sub " in chunk or "<phoneme " in chunk:
            # Already contains SSML tags, don't escape
            pass
        else:
            # Escape XML entities for plain text
            chunk = self._escape_ssml(chunk)

        return f"""<speak version="1.0" xml:lang="en-GB" xmlns="http://www.w3.org/2001/10/synthesis">
  <voice name="{self.voice}">
    <prosody rate="{self.rate}" pitch="{self.pitch}">
      {chunk}
    </prosody>
  </voice>
</speak>"""

    def _escape_ssml(self, text: str) -> str:
        """Escape XML special characters"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _wav_looks_ok(self, path: Path) -> bool:
        """Check if WAV file is valid"""
        return path.exists() and path.stat().st_size >= self.min_valid_wav_bytes

    def _synthesize_chunk(self, ssml: str, output_wav: Path, chunk_index: int, total_chunks: int):
        """Synthesize single chunk with retries"""
        audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_wav))
        synth = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config,
            audio_config=audio_config
        )

        try:
            for attempt in range(1, self.max_retries + 1):
                result = synth.speak_ssml_async(ssml).get()

                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    print(f"✓ Chunk {chunk_index}/{total_chunks}")
                    return

                if result.reason == speechsdk.ResultReason.Canceled:
                    details = result.cancellation_details
                    print(f"✗ Chunk {chunk_index} attempt {attempt}/{self.max_retries} CANCELED")
                    print(f"  Reason: {details.reason}")
                    print(f"  Details: {details.error_details}")

                    if attempt < self.max_retries:
                        time.sleep(self.retry_backoff_sec * attempt)
                        continue

                    raise RuntimeError(f"Failed to synthesize chunk {chunk_index} after {self.max_retries} attempts")

            raise RuntimeError(f"Unexpected result reason: {result.reason}")
        finally:
            # CRITICAL: Close synthesizer to release file handles (Windows file locking fix)
            # Must be done before any file cleanup operations
            del synth
            del audio_config
            gc.collect()  # Force garbage collection to release file handles
            time.sleep(0.1)  # Give Windows time to release handles

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
                # Apply noise gate to remove "pierdzenie" artifacts from TTS
                "-af", "agate=threshold=-40dB:ratio=2:attack=5:release=50",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg concat failed: {e.stderr.decode() if e.stderr else 'unknown'}")
        finally:
            if files_txt.exists():
                files_txt.unlink()

    def _normalize_loudness(self, input_wav: Path, output_wav: Path):
        """Apply loudness normalization using ffmpeg"""
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(input_wav),
                "-af", "loudnorm=I=-19:TP=-2:LRA=16",
                str(output_wav)
            ], check=True, capture_output=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Loudness normalization failed: {e.stderr.decode() if e.stderr else 'unknown'}")
