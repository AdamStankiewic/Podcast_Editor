# Stability & Architecture Audit Report

**Date:** 2026-03-06
**Application:** Podcast Language Converter
**Scope:** Full codebase stability audit — crash analysis, memory safety, resilience, performance

---

## Executive Summary

The application stopped unexpectedly during an overnight run. After a complete code audit, **17 issues** were identified ranging from critical crash-causing bugs to architectural weaknesses that make the system fragile for long-running jobs. The most likely cause of the overnight crash is a combination of **uncontrolled GPU/RAM exhaustion** from accumulated model memory across languages, **atomic write failures** corrupting job state, and **hanging FFmpeg subprocesses with no timeout** that silently block the pipeline.

---

## Part 1: Most Likely Causes of the Overnight Stop

### Cause #1 — GPU Out-of-Memory (OOM) Kill (Most Probable)

**File:** `backend/services/audio_postprocessing.py`, `backend/services/chatterbox_tts.py`

The `_cleanup_gpu_memory()` in `tasks.py` only resets the `AudioPostProcessingService` singleton (Resemble Enhance state). It does **not** unload the Chatterbox TTS model, which is created as a local variable inside `generate_tts()` in `tts_step.py` and has no reference retained:

```python
# tts_step.py — provider is created but never explicitly unloaded
provider = get_tts_provider(provider_type, model_variant=model_variant, ...)
result = provider.generate_audio(...)
# provider goes out of scope — but PyTorch tensors may remain cached in CUDA
```

After Language 1 (PL) finishes TTS, the Chatterbox multilingual model (~500M params) remains in CUDA cache. When Language 2 (FR) loads **another** Chatterbox instance, VRAM is effectively doubled. On a 16 GB GPU (e.g., RTX 4090), loading 3 languages sequentially without explicit CUDA cache clearing between TTS steps will trigger an OOM kill by the Linux kernel.

**Additionally**, in `docker-compose.yml` the worker is launched with `--concurrency=2`:
```yaml
command: celery -A backend.workers.celery_config:celery_app worker --loglevel=info --concurrency=2
```
Two concurrent workers, each loading GPU models, will exhaust VRAM on virtually any consumer GPU.

---

### Cause #2 — FFmpeg Subprocess Hang (No Timeout)

**File:** `backend/services/render.py`, `backend/services/audio_postprocessing.py`

Every FFmpeg call in the render pipeline uses `subprocess.run()` without a `timeout` argument:

```python
# render.py — _process_video(), _merge_video_audio(), _mix_audio_with_ducking()
result = subprocess.run(cmd, capture_output=True, text=True)   # No timeout!
result = subprocess.run(cmd, check=True, capture_output=True)  # No timeout!
```

If FFmpeg hangs waiting for GPU resources (NVENC queue full, GPU OOM), disk I/O stalls, or a network filesystem delays, the task blocks **forever**. With the 24-hour global Celery limit as the only backstop, the pipeline stalls overnight and the worker appears frozen.

---

### Cause #3 — Corrupted Job State JSON (Non-Atomic Writes + I/O Storm)

**File:** `backend/services/storage.py:75-87`

`add_log()` performs a full **read-modify-write** of `job_state.json` on every single log call:

```python
def add_log(self, job_id: str, message: str, level: str = "INFO"):
    job = self.load_job_state(job_id)   # READ entire JSON
    job.logs.append(log_entry)
    self.save_job_state(job)            # WRITE entire JSON — NOT atomic
```

During TTS generation for a 1-hour podcast, `add_log()` is called hundreds of times (once per chunk progress update). `save_job_state()` opens the file with `open("w")` and writes directly — if the process is killed mid-write, the JSON file is left **truncated and unparseable**. On the next run, `load_job_state()` returns `None` (silently), and the orchestrator logs "Job not found" and returns `{"error": "Job not found"}` — the job effectively disappears.

---

### Cause #4 — Celery Dynamic Time Limits Are Silently Ignored

**File:** `backend/workers/tasks.py:163-165`, `317-318`

The code attempts to set per-task time limits dynamically:

```python
# tasks.py — this does NOT work in Celery
self.time_limit = limits['hard_limit']
self.soft_time_limit = limits['soft_limit']
```

In Celery, `time_limit` and `soft_time_limit` are **worker-side configurations** set when the worker processes a task. Setting them as instance attributes on the task object at runtime has **no effect** on the running worker process. The actual limit in effect is the global `task_time_limit=86400` (24 hours) from `celery_config.py`, regardless of video duration. A 3-language job on an 84-minute video is estimated at 7.7 hours — the 24-hour limit provides no safety net against the real failure modes.

---

### Cause #5 — Worker Restart Mid-Job (`worker_max_tasks_per_child=10`)

**File:** `backend/workers/celery_config.py:36`

```python
worker_max_tasks_per_child=10,  # Restart worker after 10 tasks
```

After 10 tasks, Celery replaces the worker process. If the 10th task boundary occurs **while processing a language** (which runs inline in the orchestrator, not as a separate Celery task — see Issue #3 below), the worker process is killed mid-render, leaving the job stuck in `RENDERING` status forever with no error logged.

---

## Part 2: Full Audit Findings

---

### Issue 1 — CRITICAL: `process_language_task` Called as Plain Python Function

**File:** `backend/workers/tasks.py:358`

```python
# WRONG — bypasses all Celery infrastructure
result = process_language_task(job_id, lang, video_duration)

# CORRECT — would use Celery's worker isolation
result = process_language_task.apply(args=[job_id, lang, video_duration])
```

**Problem:** `process_language_task` is decorated with `@celery_app.task`, but it is invoked as a plain function inside `process_podcast_task`. This means:
- The language task runs **in the same process** as the orchestrator — no process isolation
- The dynamically set `self.time_limit` / `self.soft_time_limit` on the language task are never used
- A GPU OOM crash in the language task propagates and kills the orchestrator too
- The Celery result backend never receives a separate result for the language task

**Fix:** Either call it directly as a function (and document that it's intentional), OR use `.apply()` for synchronous in-process execution that still respects task machinery:

```python
result = process_language_task.apply(
    args=[job_id, lang, video_duration],
    time_limit=limits['hard_limit'],
    soft_time_limit=limits['soft_limit']
).get()
```

---

### Issue 2 — CRITICAL: `add_log()` I/O Storm + Non-Atomic Writes = State Corruption

**File:** `backend/services/storage.py:75-87`

**Problem:** Every log call does a full disk read + write of the entire JSON state. For a 3-language, 1-hour podcast, `add_log()` is called ~800 times during TTS (one per chunk × 3 languages). This means **1,600 disk read/write cycles** just for logging. The write is non-atomic: a crash between `open("w")` and the final `f.close()` corrupts the file.

**Dangerous code pattern:**
```python
def add_log(self, job_id: str, message: str, level: str = "INFO"):
    job = self.load_job_state(job_id)  # Reads full JSON
    job.logs.append(log_entry)
    self.save_job_state(job)           # Writes full JSON non-atomically
    # Also writes to pipeline.log (unclosed handle on crash)
    with log_file.open("a", ...) as f:
        f.write(log_entry + "\n")
```

**Fix — Atomic write + append-only logging:**
```python
def save_job_state(self, job: Job):
    """Atomic save using temp-file + rename pattern"""
    job_dir = self.get_job_dir(job.id)
    state_file = job_dir / "job_state.json"
    tmp_file = state_file.with_suffix(".json.tmp")

    job.updated_at = datetime.utcnow()
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(job.model_dump(mode='json'), f, indent=2, default=str)
    tmp_file.replace(state_file)  # Atomic on POSIX filesystems

def add_log(self, job_id: str, message: str, level: str = "INFO"):
    """Append only to log file — do NOT read/write full state on every log"""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{level}] {message}"

    log_file = self.get_job_dir(job_id) / "pipeline.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

    # State update: only when status/progress changes, not for every log
```

---

### Issue 3 — CRITICAL: No Stack Traces in Error Logging

**Files:** All pipeline steps and task files

Throughout the codebase, exceptions are caught and only `str(e)` is stored:

```python
except Exception as e:
    storage.add_log(job_id, f"❌ PIPELINE FAILED (orchestrator): {e}", "ERROR")
    # The full traceback — file, line number, call stack — is lost forever
```

After an overnight crash, it is **impossible to diagnose** which line caused the failure without a full traceback.

**Fix — Always log full tracebacks:**
```python
import traceback

except Exception as e:
    tb = traceback.format_exc()
    storage.add_log(job_id, f"❌ PIPELINE FAILED:\n{tb}", "ERROR")
    # Also write to a separate crash file for persistence:
    crash_log = storage.get_job_dir(job_id) / "crash.log"
    crash_log.write_text(f"[{datetime.utcnow()}] {tb}", encoding="utf-8")
```

---

### Issue 4 — CRITICAL: FFmpeg Subprocesses Have No Timeout

**Files:** `backend/services/render.py`, `backend/services/audio_postprocessing.py`, `backend/services/chatterbox_tts.py`

**Problem:** All FFmpeg calls lack `timeout=` parameter. A hung FFmpeg process stalls the entire pipeline forever:

```python
# render.py — no timeout on any of these
subprocess.run(cmd, capture_output=True, text=True)           # _process_video
subprocess.run(cmd, check=True, capture_output=True, text=True) # _merge_video_audio
subprocess.run([...], check=True, capture_output=True)          # audio_postprocessing
```

**Fix — Add explicit timeouts based on expected operation duration:**
```python
# For a 2-hour video render, 4 hours is a safe upper bound
VIDEO_RENDER_TIMEOUT = int(os.getenv("VIDEO_RENDER_TIMEOUT", str(4 * 3600)))
AUDIO_PROCESS_TIMEOUT = int(os.getenv("AUDIO_PROCESS_TIMEOUT", str(2 * 3600)))
FFPROBE_TIMEOUT = 30

# Usage:
try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=VIDEO_RENDER_TIMEOUT
    )
except subprocess.TimeoutExpired:
    result.kill()
    raise RuntimeError(f"FFmpeg timed out after {VIDEO_RENDER_TIMEOUT}s")
```

---

### Issue 5 — HIGH: Chatterbox Model Not Unloaded Between Languages

**File:** `backend/workers/tasks.py:20-45`, `backend/pipeline/tts_step.py`

`_cleanup_gpu_memory()` resets `audio_postprocessing._audio_postprocessing_service = None` but does **not** clean up the Chatterbox model, which is held inside the local `provider` variable in `generate_tts()`. Python's garbage collector may not immediately release CUDA tensors, and `torch.cuda.empty_cache()` alone is insufficient if the Python object still holds references.

**Fix — Explicitly unload TTS provider after use:**
```python
# tts_step.py — after generate_audio(), unload the model
try:
    result = provider.generate_audio(...)
    return {...}
finally:
    # Explicitly unload to free VRAM before next language
    if hasattr(provider, 'unload_model'):
        provider.unload_model()
    del provider
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```

---

### Issue 6 — HIGH: No Retry with Backoff for OpenAI API Calls

**File:** `backend/services/translate.py:394-433`

The translation service has only 2 retries with **no delay** between them:
```python
max_retries = 2
for attempt in range(max_retries):
    try:
        response = self.client.chat.completions.create(...)
        ...
    except Exception as e:
        if attempt == max_retries - 1:
            raise RuntimeError(...)
        print(f"Retry {attempt+1}/{max_retries}...")
        # No sleep! Immediate retry hits rate limit again
```

OpenAI returns `429 RateLimitError` with a `Retry-After` header. Immediate retries will fail again.

**Fix — Exponential backoff with jitter:**
```python
import time
import random

max_retries = 5
for attempt in range(max_retries):
    try:
        response = self.client.chat.completions.create(...)
        return response.choices[0].message.content.strip()
    except openai.RateLimitError as e:
        if attempt == max_retries - 1:
            raise
        wait = (2 ** attempt) + random.uniform(0, 1)
        print(f"Rate limited. Waiting {wait:.1f}s before retry {attempt+1}/{max_retries}")
        time.sleep(wait)
    except openai.APIConnectionError as e:
        if attempt == max_retries - 1:
            raise
        time.sleep(2 ** attempt)
```

---

### Issue 7 — HIGH: Bare `except:` Swallows All Errors in WebSocket Broadcast

**File:** `backend/app.py:57-60`

```python
async def broadcast(self, message: dict):
    for connection in self.active_connections:
        try:
            await connection.send_json(message)
        except:   # Catches EVERYTHING including KeyboardInterrupt, SystemExit
            pass  # Silent failure — dead connections accumulate forever
```

**Problems:**
1. Dead WebSocket connections are never removed from `active_connections` — the list grows indefinitely, consuming memory
2. `KeyboardInterrupt` and `SystemExit` are caught and suppressed — prevents clean shutdown
3. No logging of connection errors

**Fix:**
```python
async def broadcast(self, message: dict):
    dead = []
    for connection in self.active_connections:
        try:
            await connection.send_json(message)
        except (WebSocketDisconnect, RuntimeError) as e:
            dead.append(connection)
    for conn in dead:
        self.active_connections.remove(conn)
```

---

### Issue 8 — HIGH: DeepFilterNet Holds All Chunks in RAM Before Writing

**File:** `backend/services/audio_postprocessing.py:276-356`

During chunk-based DeepFilterNet processing, all enhanced chunks are accumulated in a Python list of PyTorch tensors:

```python
enhanced_chunks = []
for i in range(num_chunks):
    enhanced_chunk = enhance(model, df_state, chunk, sr)
    enhanced_chunks.append({'audio': enhanced_chunk, ...})  # All in RAM!

# Then assembled after all chunks are done
enhanced = torch.zeros((1, total_samples))
for chunk_data in enhanced_chunks:
    ...
```

For a 90-minute podcast with 5-minute chunks = 18 chunks. Each chunk at 48kHz mono = ~14M samples × 4 bytes = ~56 MB. Total: ~1 GB of tensors held in RAM simultaneously **in addition to** the model itself.

**Fix — Write chunks to disk immediately and use streaming concatenation:**
```python
chunk_files = []
for i in range(num_chunks):
    enhanced_chunk = enhance(model, df_state, chunk, sr)
    chunk_file = temp_dir / f"chunk_{i:03d}.wav"
    torchaudio.save(str(chunk_file), enhanced_chunk.cpu(), sr)
    chunk_files.append(chunk_file)
    del enhanced_chunk  # Free immediately
    gc.collect()

# Concatenate on disk using ffmpeg (no RAM accumulation)
self._concat_audio_files(chunk_files, output_wav)
```

---

### Issue 9 — MEDIUM: `docker-compose.yml` Worker Concurrency = 2 with GPU Models

**File:** `docker-compose.yml:65`

```yaml
command: celery ... worker --loglevel=info --concurrency=2
```

With `worker_prefetch_multiplier=1` and sequential language processing, this creates 2 concurrent Celery worker processes. If two jobs arrive simultaneously, both will load Chatterbox + Resemble Enhance models, potentially requiring 2× the VRAM. On a 16 GB GPU:
- Chatterbox Multilingual: ~4 GB VRAM
- Resemble Enhance: ~2 GB VRAM
- 2 workers: **~12 GB** just for models, leaving only 4 GB for activations

For a 90-minute podcast (large batch), activation memory can exceed the remaining 4 GB, causing an OOM kill.

**Fix — Reduce to `--concurrency=1` for GPU-heavy workloads:**
```yaml
command: celery ... worker --loglevel=info --concurrency=1 -Q gpu_queue
```

---

### Issue 10 — MEDIUM: `get_audio_postprocessing()` Singleton Ignores Repeated Parameters

**File:** `backend/services/audio_postprocessing.py:429-444`

```python
_audio_postprocessing_service = None

def get_audio_postprocessing(enable_ai_enhance=True, ...) -> AudioPostProcessingService:
    global _audio_postprocessing_service
    if _audio_postprocessing_service is None:
        _audio_postprocessing_service = AudioPostProcessingService(...)
    return _audio_postprocessing_service  # Returns cached instance ignoring new params!
```

If any code path calls this function with `enable_ai_enhance=False` first (e.g., from a test), subsequent calls with `enable_ai_enhance=True` silently get the cached instance with AI disabled. There is no warning.

**Fix — Either drop the singleton pattern, or validate params match:**
```python
def get_audio_postprocessing(**kwargs) -> AudioPostProcessingService:
    global _audio_postprocessing_service
    if _audio_postprocessing_service is None:
        _audio_postprocessing_service = AudioPostProcessingService(**kwargs)
    elif kwargs:  # If called with explicit params that differ, warn
        import warnings
        warnings.warn("get_audio_postprocessing() called with params but singleton already exists. Params ignored.")
    return _audio_postprocessing_service
```

---

### Issue 11 — MEDIUM: No Chatterbox TTS Timeout Per Chunk

**File:** `backend/services/chatterbox_tts.py:259`

```python
wav = self.model.generate(text, **gen_kwargs)  # No timeout
```

A single TTS chunk generation can take minutes on CPU or seconds on GPU. If the model hangs (GPU lock, CUDA error, deadlock in PyTorch), the task blocks indefinitely with no way to detect it or recover.

**Fix — Use `concurrent.futures.ThreadPoolExecutor` with a timeout:**
```python
import concurrent.futures

def _synthesize_chunk_with_timeout(self, text, config, ref_audio, chunk_index, total_chunks, timeout=300):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(self._synthesize_chunk, text, config, ref_audio, chunk_index, total_chunks)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(f"TTS chunk {chunk_index} timed out after {timeout}s")
```

---

### Issue 12 — MEDIUM: No Disk Space Check Before Operations

**Files:** `backend/pipeline/download.py`, `backend/pipeline/render_step.py`

No disk space validation before downloading (up to 10 GB for a 2-hour 4K video) or rendering (intermediate files can be 3× output size). If disk fills during an FFmpeg render, `ffmpeg` writes a truncated/corrupted file and exits with an error that may or may not be caught properly.

**Fix — Pre-flight disk check:**
```python
import shutil

def _check_disk_space(path: Path, required_bytes: int, label: str = ""):
    free = shutil.disk_usage(path).free
    if free < required_bytes:
        raise RuntimeError(
            f"Insufficient disk space for {label}: "
            f"need {required_bytes / 1e9:.1f} GB, "
            f"have {free / 1e9:.1f} GB free at {path}"
        )

# Before download (estimate: video_duration * 10 MB/min for 1080p)
estimated_bytes = int(video_duration * 10 * 1024 * 1024 / 60)
_check_disk_space(video_path.parent, estimated_bytes * 3, "download + render")
```

---

### Issue 13 — MEDIUM: `worker_max_tasks_per_child` Can Kill Mid-Job

**File:** `backend/workers/celery_config.py:36`

```python
worker_max_tasks_per_child=10,  # Restart worker after 10 tasks
```

Because `process_language_task` runs inline inside `process_podcast_task`, a single podcast job counts as 1 task toward the limit, not 4 (one per language). However, if multiple jobs have been processed and the 10th task boundary falls on a long-running job, the child process is recycled mid-execution.

**Fix — Either increase the limit substantially or set it to 0 (no recycling):**
```python
worker_max_tasks_per_child=1,  # Restart after each job to prevent any memory accumulation
# OR
worker_max_tasks_per_child=0,  # Never restart (rely on explicit GPU cleanup instead)
```

---

### Issue 14 — MEDIUM: No Heartbeat During Long GPU Operations

**Files:** `backend/pipeline/enhance_step.py`, `backend/pipeline/tts_step.py`

During Resemble Enhance (~40 min) or Chatterbox TTS (~60+ min), there are no periodic heartbeat signals to Celery. Celery's `worker_heartbeat` (default 120s) monitors worker liveness, but if the task is deeply blocked inside a PyTorch CUDA operation, the heartbeat may miss. Celery's `task_acks_late=True` would help re-queue the task on worker death.

**Fix — Enable late acknowledgment and add periodic progress updates:**
```python
# celery_config.py
celery_app.conf.update(
    task_acks_late=True,         # Only ack after successful completion
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    worker_send_task_events=True,
)

# In long-running operations, periodically send a heartbeat:
from celery import current_task
if current_task:
    current_task.update_state(state='PROGRESS', meta={'step': 'enhancing', 'chunk': i})
```

---

### Issue 15 — MEDIUM: Translation `_ai_quality_validator` Truncates Text to 40k chars

**File:** `backend/services/translate.py:773`

```python
POLSKIE TŁUMACZENIE ({text_length} znaków):
{translated_text[:40000]}   # Hard truncation!
```

The prompt tells GPT the text is `text_length` chars long but sends only the first 40,000 chars. GPT is asked to return the "corrected full text" but only sees a truncated version. The code does check if the corrected text is shorter than 90% of original and reverts, but this means the quality check silently no-ops for any text > 35,000 chars, with a misleading log message.

**Fix — Either split the quality check into chunks, or remove this quality check for long texts entirely (currently the function already has a `len > 35000` guard that skips it, so the `[:40000]` truncation in the prompt is unreachable for texts that pass the guard — but this creates a fragile dependency on two separate length checks staying in sync).**

---

### Issue 16 — LOW: `download.py` Has Bare `except:` That Loses Metadata Error

**File:** `backend/pipeline/download.py:51-57`

```python
try:
    info = yt_service.get_video_info(url)
    ...
    return {"video_id": video_id, "title": info["title"], "duration": info["duration"], ...}
except:   # Bare except — catches everything, logs nothing
    video_id = yt_service.extract_video_id(url)
    return {"video_id": video_id, "video_path": str(video_path), "from_cache": False}
    # duration is MISSING — defaults to 600s (10 min) in orchestrator
    # This means time limit calculation for a 2-hour video uses 10-min estimate
```

**Problem:** If metadata fetch fails silently, `video_duration` defaults to 600s (10 minutes). For a 2-hour video, the `calculate_language_task_limits()` function would calculate a drastically underestimated time limit. Even though these limits are currently not enforced (Issue #1 above), this also affects progress logging.

**Fix:**
```python
except Exception as e:
    storage.add_log(job_id, f"Warning: metadata fetch failed after download: {e}", "WARNING")
    video_id = yt_service.extract_video_id(url)
    return {"video_id": video_id, "video_path": str(video_path), "from_cache": False}
```

---

### Issue 17 — LOW: Temp Directories Not Cleaned on SIGKILL

**Files:** `backend/services/render.py:86-153`, `backend/services/audio_postprocessing.py:91-162`

Both services create temp directories and clean them in `except` blocks. But a SIGKILL (OOM kill, Docker stop) bypasses `finally` and `except` handlers entirely. Over multiple runs, orphaned `_render_*/` and `_postprocessing_*/` directories accumulate and consume disk space.

**Fix — Use `atexit` or a startup cleanup scan:**
```python
# At worker startup, clean up any orphaned temp dirs from previous runs
def cleanup_orphaned_temp_dirs(base_path: Path):
    for d in base_path.glob("_render_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    for d in base_path.glob("_postprocessing_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    for d in base_path.glob("_temp_chatterbox_*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
```

---

## Part 3: Top 10 Stability Improvements (Priority Order)

| # | Improvement | Impact | Effort |
|---|-------------|--------|--------|
| 1 | **Add full stack traces to all error logging** | Diagnose any future crash | Low |
| 2 | **Atomic JSON writes** (`tmp` + `rename`) for job state | Prevent state corruption | Low |
| 3 | **Add `timeout=` to all FFmpeg subprocess calls** | Prevent infinite hangs | Low |
| 4 | **Explicitly unload Chatterbox model after TTS** | Prevent GPU OOM between languages | Low |
| 5 | **Set `--concurrency=1` in docker-compose** | Prevent dual-GPU-model OOM | Trivial |
| 6 | **Decouple `add_log()` from full state read/write** | Eliminate I/O storm + corruption risk | Medium |
| 7 | **Add exponential backoff to OpenAI API calls** | Prevent translation failures on rate limits | Low |
| 8 | **Set `task_acks_late=True` and `task_reject_on_worker_lost=True`** | Enable job re-queuing on worker crash | Trivial |
| 9 | **Add pre-flight disk space check** | Prevent silent mid-render failures | Low |
| 10 | **Stream DeepFilterNet chunks to disk immediately** | Prevent RAM exhaustion on long podcasts | Medium |

---

## Part 4: Top 5 Critical Bugs to Fix First

### Bug 1 — Non-atomic job state writes (data corruption on crash)
**File:** `storage.py:44-45`
**Risk:** Job vanishes after overnight crash — primary reason the app appears to "stop"
**Fix:** Use temp-file + atomic rename in `save_job_state()`

### Bug 2 — No FFmpeg subprocess timeouts (infinite hangs)
**File:** `render.py`, `audio_postprocessing.py`
**Risk:** Any FFmpeg stall blocks the pipeline indefinitely
**Fix:** Add `timeout=VIDEO_RENDER_TIMEOUT` to all `subprocess.run()` calls

### Bug 3 — Chatterbox model not unloaded between languages (VRAM leak)
**File:** `tts_step.py`, `tasks.py:_cleanup_gpu_memory()`
**Risk:** GPU OOM after language 1 kills language 2/3 processing
**Fix:** Call `provider.unload_model()` in a `finally` block in `generate_tts()`

### Bug 4 — No stack traces logged on exceptions
**File:** All pipeline files
**Risk:** Impossible to diagnose production failures without traces
**Fix:** Use `traceback.format_exc()` in all `except Exception` handlers

### Bug 5 — Worker concurrency=2 with single GPU
**File:** `docker-compose.yml:65`
**Risk:** Two concurrent GPU-model loads exhaust VRAM, causing OOM kill
**Fix:** Set `--concurrency=1` immediately

---

## Part 5: Architecture Improvement Recommendations

### 5.1 Separate GPU Task Queue

```python
# celery_config.py
celery_app.conf.update(
    task_routes={
        'process_podcast': {'queue': 'orchestrator'},
        'process_language': {'queue': 'gpu_worker'},
    }
)
```

Run a dedicated GPU worker with `--concurrency=1 -Q gpu_worker` and a separate CPU worker for the orchestrator.

### 5.2 Job State as Two Files

Separate the frequently-appended logs from the infrequently-changed job metadata:

```
data/<job_id>/
  job_state.json      # Status, artifacts, progress only — written rarely
  pipeline.log        # Append-only log file — never read into memory
```

This eliminates the read-modify-write cycle for logging entirely.

### 5.3 Watchdog Process

A simple watchdog that monitors job states and alerts (or restarts) if a job has been `IN_PROGRESS` for too long without a log entry:

```python
# scripts/watchdog.py
def check_stuck_jobs(max_silence_minutes=30):
    for job in storage.get_all_jobs():
        if job.status in [TRANSLATING, GENERATING_TTS, ENHANCING_AUDIO, RENDERING]:
            last_log_time = parse_last_log_timestamp(job.logs[-1])
            if (datetime.utcnow() - last_log_time).total_seconds() > max_silence_minutes * 60:
                alert(f"Job {job.id} has been silent for {max_silence_minutes}+ minutes!")
```

### 5.4 Celery Flower for Real-Time Monitoring

```yaml
# docker-compose.yml
flower:
  image: mher/flower
  command: celery flower --broker=redis://redis:6379/0 --port=5555
  ports:
    - "5555:5555"
```

Flower provides a web dashboard showing active tasks, worker health, and task history — essential for diagnosing overnight failures.

### 5.5 Health Check Endpoint Enhancement

The current `/health` endpoint returns `{"status": "healthy"}` regardless of actual system state. It should verify Redis connectivity and check for stuck jobs:

```python
@app.get("/health")
async def health_check():
    checks = {}

    # Check Redis
    try:
        from backend.workers.celery_config import celery_app
        celery_app.control.ping(timeout=2)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unreachable"

    # Check for stuck jobs
    stuck = [j for j in storage.get_all_jobs()
             if j.status not in [JobStatus.DONE, JobStatus.ERROR, JobStatus.QUEUED]
             and (datetime.utcnow() - j.updated_at).total_seconds() > 3600]
    checks["stuck_jobs"] = len(stuck)

    overall = "healthy" if checks["redis"] == "ok" and checks["stuck_jobs"] == 0 else "degraded"
    return {"status": overall, "checks": checks, "timestamp": datetime.utcnow().isoformat()}
```

---

## Summary Checklist

- [ ] **IMMEDIATE** Set `--concurrency=1` in docker-compose worker command
- [ ] **IMMEDIATE** Add `traceback.format_exc()` to all except blocks
- [ ] **HIGH** Make `save_job_state()` atomic (tmp + rename)
- [ ] **HIGH** Add `timeout=` to all `subprocess.run()` calls in render.py and audio_postprocessing.py
- [ ] **HIGH** Unload Chatterbox model explicitly after TTS step
- [ ] **HIGH** Separate log appending from job state saves
- [ ] **MEDIUM** Add OpenAI exponential backoff (5 retries, 2^n seconds)
- [ ] **MEDIUM** Enable `task_acks_late=True`, `task_reject_on_worker_lost=True` in Celery
- [ ] **MEDIUM** Add pre-flight disk space checks
- [ ] **MEDIUM** Stream DeepFilterNet chunks to disk instead of accumulating in RAM
- [ ] **LOW** Add startup cleanup of orphaned temp directories
- [ ] **LOW** Fix bare `except:` in WebSocket broadcast (remove dead connections)
- [ ] **LOW** Add Celery Flower to docker-compose for operational visibility
- [ ] **LOW** Enhance `/health` endpoint to check real system state
- [ ] **LOW** Add watchdog script for stuck job detection
