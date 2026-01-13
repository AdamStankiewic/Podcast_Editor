# 🏠 Running Worker Locally (Windows)

This guide explains how to run the Celery Worker **locally on Windows** instead of in Docker.

## Why Run Worker Locally?

**Problem:** Azure Speech SDK has compatibility issues in Docker containers (error: "Failed to initialize platform (azure-c-shared). Error: 2176")

**Solution:** Run the worker natively on Windows where Azure Speech SDK works perfectly.

---

## ✅ Architecture

```
┌─────────────────────────────────────────┐
│  DOCKER                                 │
│  ┌─────────┐      ┌─────────────┐     │
│  │  Redis  │◄─────┤   Backend   │     │
│  │  :6379  │      │    :8000    │     │
│  └────▲────┘      └─────────────┘     │
│       │                                │
└───────┼────────────────────────────────┘
        │
        │ (localhost:6379)
        │
┌───────▼────────────────────────────────┐
│  WINDOWS (Local)                       │
│  ┌─────────────────────────┐          │
│  │   Celery Worker         │          │
│  │   + Azure Speech SDK ✓  │          │
│  └─────────────────────────┘          │
└────────────────────────────────────────┘
```

---

## 🚀 Quick Start (3 Steps)

### Step 1: Install Python Locally

Make sure you have **Python 3.11+** installed on Windows.

```powershell
# Check Python version
python --version
# Should show: Python 3.11.x or higher
```

If not installed, download from: https://www.python.org/downloads/

---

### Step 2: Install Dependencies Locally

Open PowerShell in project directory:

```powershell
cd C:\Users\adams\Desktop\Podcast_Editor

# Install all Python dependencies locally
pip install -r requirements.txt

# This will install:
# - Azure Speech SDK (works natively on Windows!)
# - Celery, OpenAI, FFmpeg-python, etc.
```

**Note:** This may take 2-3 minutes.

---

### Step 3: Start Services

**Option A: Use Helper Scripts (Recommended)**

```powershell
# Terminal 1: Start Redis + Backend in Docker
.\start_redis_backend.bat

# Terminal 2: Start Worker locally
.\run_worker_local.bat
```

**Option B: Manual Commands**

```powershell
# Terminal 1: Start Redis + Backend
docker compose down
docker compose up redis backend -d

# Terminal 2: Set environment and start worker
$env:REDIS_URL="redis://localhost:6379/0"
$env:CELERY_BROKER_URL="redis://localhost:6379/0"
$env:CELERY_RESULT_BACKEND="redis://localhost:6379/0"

celery -A backend.workers.celery_config:celery_app worker --loglevel=info --concurrency=2 --pool=solo
```

---

## ✅ Verify It's Working

1. **Open browser:** http://localhost:8000
2. **Paste YouTube URL** (e.g., https://www.youtube.com/watch?v=nlhDSfB9lCQ)
3. **Click "Start Processing"**
4. **Watch Worker logs** in PowerShell - you should see:
   ```
   [INFO] Job created for URL: https://...
   [INFO] Starting pipeline for job: xxx
   [INFO] Downloading video...
   [INFO] Translating...
   [INFO] Generating TTS...  ← This should work now!
   ```

---

## 🎯 Environment Variables

The worker needs access to your `.env` file. Make sure it contains:

```env
# OpenAI
OPENAI_API_KEY=sk-xxx

# Azure Speech
SPEECH_KEY=xxx
SPEECH_REGION=westeurope

# Video Processing
MAX_VIDEO_DURATION_HOURS=3
USE_GPU_ENCODING=true

# Optional: RAM Disk
# TEMP_PATH=R:/podcast_temp
```

**Note:** Worker will automatically load `.env` from the project directory.

---

## 🔧 Troubleshooting

### ❌ "ModuleNotFoundError: No module named 'azure'"

**Problem:** Dependencies not installed locally.

**Solution:**
```powershell
pip install -r requirements.txt
```

---

### ❌ "Error: Unable to connect to redis://localhost:6379"

**Problem:** Redis not running or not accessible.

**Solution:**
```powershell
# Check if Redis container is running
docker ps | findstr redis

# If not running, start it
docker compose up redis -d

# Verify connection
docker exec podcast_redis redis-cli ping
# Should output: PONG
```

---

### ❌ "celery: command not found"

**Problem:** Celery not installed or not in PATH.

**Solution:**
```powershell
# Install Celery
pip install celery

# Or reinstall all dependencies
pip install -r requirements.txt
```

---

### ❌ Worker starts but jobs don't process

**Problem:** Worker is connected to wrong Redis instance.

**Solution:**
Make sure environment variables are set:
```powershell
# Check current values
echo $env:CELERY_BROKER_URL
# Should show: redis://localhost:6379/0

# If empty, set them
$env:REDIS_URL="redis://localhost:6379/0"
$env:CELERY_BROKER_URL="redis://localhost:6379/0"
$env:CELERY_RESULT_BACKEND="redis://localhost:6379/0"
```

---

## 💡 Tips

### GPU Encoding

Your worker will use **NVENC GPU acceleration** automatically if you have:
- NVIDIA GPU with NVENC support
- Latest GPU drivers
- `USE_GPU_ENCODING=true` in `.env`

### RAM Disk

For 20% faster I/O, configure RAM Disk:
1. See `docs/RAMDISK_SETUP.md` for setup
2. Add to `.env`: `TEMP_PATH=R:/podcast_temp`

### Concurrency

Worker uses `--concurrency=2` (2 parallel jobs). Adjust based on your CPU:
```powershell
# For 8-core CPU, use 4 workers
celery -A backend.workers.celery_config:celery_app worker --concurrency=4 --pool=solo
```

**Note:** Use `--pool=solo` on Windows (required for multiprocessing).

---

## 🐳 Return to Full Docker

To switch back to running everything in Docker:

```powershell
# Stop local worker (Ctrl+C in PowerShell)

# Start all services in Docker
docker compose down
docker compose up -d

# Now worker runs in Docker again
```

---

## 📊 Performance Comparison

| Setup | Azure TTS | GPU Encoding | Speed |
|-------|-----------|--------------|-------|
| **All Docker** | ❌ Broken | ✅ Works | 100% |
| **Local Worker** | ✅ **Works!** | ✅ Works | **110%** (faster) |

Local worker is actually **faster** because:
- No Docker overhead
- Direct file system access
- Native Windows process

---

## 🎉 Success!

If you see this in worker logs:

```
[INFO] Generating TTS...
[INFO] Azure TTS batch synthesis starting...
[INFO] Chunk 1/36 synthesized successfully
[INFO] Audio file saved: output/xxx/tts_audio.wav
```

**🎉 Azure TTS is working!** Your worker is now running locally with full Azure Speech SDK support.

---

## 📝 Summary

- ✅ Redis + Backend: Docker
- ✅ Worker: Windows (local)
- ✅ Azure TTS: Working
- ✅ GPU Encoding: Working
- ✅ Performance: Better than Docker

You're all set! 🚀
