# Local Setup Guide (No Docker)

This guide explains how to run the Podcast Editor **completely locally on Windows** without Docker (except optionally for Redis).

## Why Local Setup?

Azure Speech SDK has compatibility issues with Docker on Windows. Running the worker locally resolves these issues while maintaining full functionality.

## Prerequisites

1. **Python 3.11 or 3.12** installed
2. **WSL (Windows Subsystem for Linux)** with Redis installed
   - Alternative: Docker Desktop (for Redis only)
3. **FFmpeg** installed and in PATH
4. **Azure Cognitive Services** credentials (SPEECH_KEY, SPEECH_REGION)

---

## Step 1: Install Redis

### Option A: WSL Redis (Recommended)

1. Open PowerShell and enter WSL:
   ```powershell
   wsl
   ```

2. Install Redis in WSL:
   ```bash
   sudo apt update
   sudo apt install redis-server
   ```

3. Exit WSL:
   ```bash
   exit
   ```

### Option B: Docker Redis (Fallback)

If WSL doesn't work, use Docker for Redis only:
```powershell
docker run -d -p 6379:6379 --name podcast_redis redis:7-alpine
```

---

## Step 2: Install Python Dependencies

1. Create virtual environment:
   ```powershell
   py -3.12 -m venv .venv
   ```

2. Activate virtual environment:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Upgrade pip and install dependencies:
   ```powershell
   python -m pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

---

## Step 3: Configure Environment

Create `.env` file in project root with your credentials:

```env
# Azure Cognitive Services
SPEECH_KEY=your_azure_speech_key_here
SPEECH_REGION=your_region_here

# OpenAI
OPENAI_API_KEY=your_openai_key_here

# Redis (local)
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Optional: Video duration limit
MAX_VIDEO_DURATION_HOURS=2
```

---

## Step 4: Verify Setup

Run the setup check script:
```powershell
.\setup_local.bat
```

This will verify:
- ✓ Python installation
- ✓ Virtual environment
- ✓ Azure Speech SDK
- ✓ .env configuration
- ✓ Redis availability
- ✓ FFmpeg installation

---

## Step 5: Start Services

### Option A: Start All Services Automatically

Run:
```powershell
.\start_all_local.bat
```

This opens 3 terminal windows:
1. **Redis** - Running on localhost:6379
2. **Backend** - FastAPI on http://localhost:8000
3. **Worker** - Celery worker for video processing

### Option B: Start Services Manually

Open **3 separate PowerShell terminals** and run:

**Terminal 1 - Redis:**
```powershell
.\start_redis_local.bat
```

**Terminal 2 - Backend:**
```powershell
.\start_backend_local.bat
```

**Terminal 3 - Worker:**
```powershell
.\start_worker_local.bat
```

---

## Step 6: Use the Application

1. Open browser to: **http://localhost:8000**

2. Paste a YouTube URL (German podcast)

3. Click "Start Processing"

4. Monitor progress in real-time

5. Download the converted video when complete

---

## Features

### Video Cache
Videos are cached after first download to avoid re-downloading:
- Cache location: `./data/_cache/videos/`
- Organized by video_id
- Automatic reuse on subsequent jobs

### URL History
Tracks which URLs have been processed:
- History file: `./data/_history/processed_urls.json`
- Warnings shown for duplicate URLs
- View history via API: `GET /api/history`

### API Endpoints

- `GET /` - Web interface
- `POST /api/jobs` - Create new job
- `GET /api/jobs/{job_id}` - Get job status
- `GET /api/history` - View URL history
- `GET /api/cache/stats` - Cache statistics
- `DELETE /api/cache/{video_id}` - Clear specific cache entry

---

## Troubleshooting

### Redis Not Starting

**WSL:**
```powershell
wsl
sudo service redis-server start
redis-cli ping  # Should return PONG
exit
```

**Docker:**
```powershell
docker start podcast_redis
```

### Azure TTS Timeout

If worker shows timeout errors during synthesis:
1. Check internet connection
2. Verify Azure credentials in .env
3. Worker has automatic retry (5 attempts with exponential backoff)
4. Longer videos may take time - be patient

### Worker Errors

Check that .env file has:
- `SPEECH_KEY` (no quotes)
- `SPEECH_REGION` (no quotes)
- No trailing spaces

### Background Music Too Loud

Adjust in `backend/services/render.py`:
```python
# Current settings: -24dB volume, 0.15 mix weight
# Increase negative value for quieter music: -30dB
```

### Overlay Not Fullscreen

The overlay PNG must have:
1. Alpha channel (transparency)
2. Will be scaled to match video dimensions automatically

---

## Performance Tips

1. **GPU Encoding**: Ensure NVIDIA GPU is available for NVENC encoding
2. **Cache Management**: Clear old cached videos to save disk space
3. **Concurrency**: Worker uses `--concurrency=2` - increase if you have more CPU cores

---

## Stopping Services

### Quick Stop
Close the terminal windows for each service

### Clean Stop

**Redis (WSL):**
```powershell
wsl redis-cli shutdown
```

**Backend/Worker:**
Press `Ctrl+C` in their respective terminals

---

## File Structure

```
Podcast_Rditor/
├── backend/
│   ├── app.py                    # FastAPI application
│   ├── pipeline/
│   │   ├── download.py           # Video download + cache
│   │   ├── translate.py          # Translation
│   │   ├── synthesize.py         # Azure TTS
│   │   └── render.py             # Video rendering
│   ├── services/
│   │   ├── video_cache.py        # Video caching
│   │   ├── url_history.py        # URL tracking
│   │   └── azure_tts_batch.py    # TTS service
│   └── workers/
│       └── celery_config.py      # Celery configuration
├── data/
│   ├── _cache/videos/            # Cached videos
│   ├── _history/                 # URL history
│   └── jobs/                     # Job artifacts
├── setup_local.bat               # Setup verification
├── start_all_local.bat           # Start all services
├── start_redis_local.bat         # Start Redis
├── start_backend_local.bat       # Start Backend
├── start_worker_local.bat        # Start Worker
└── .env                          # Configuration (create this)
```

---

## Notes

- First video download takes ~3-5 minutes depending on length
- Subsequent same video uses cache: ~30 seconds
- Translation preserves timing (ratio ~0.95-1.10)
- Azure TTS generates high-quality Polish narration
- Background music automatically ducked when voice plays
- Overlay scales to fullscreen with transparency

---

## Support

For issues:
1. Check `.\setup_local.bat` output
2. Review terminal logs (Redis, Backend, Worker)
3. Check `.env` configuration
4. Verify Azure credentials are valid
