@echo off
REM ========================================================
REM Celery Worker - Local Execution (Windows)
REM ========================================================
REM This script runs the Celery worker locally on Windows
REM instead of in Docker. This fixes Azure Speech SDK issues.
REM
REM Prerequisites:
REM   1. Redis and Backend running in Docker
REM   2. Python 3.11+ installed locally
REM   3. Dependencies installed: pip install -r requirements.txt
REM ========================================================

echo.
echo ========================================================
echo   Starting Celery Worker Locally (Azure TTS Fix)
echo ========================================================
echo.

REM Check if Redis is running
echo [1/3] Checking Redis connection...
docker ps | findstr podcast_redis >nul
if errorlevel 1 (
    echo ERROR: Redis container is not running!
    echo Please start it with: docker compose up redis backend -d
    pause
    exit /b 1
)
echo       Redis is running!

REM Check if dependencies are installed
echo [2/3] Checking Azure Speech SDK...
python -c "import azure.cognitiveservices.speech" 2>nul
if errorlevel 1 (
    echo ERROR: Azure Speech SDK not installed locally!
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)
echo       Azure Speech SDK installed!

REM Set environment variables for local worker
echo [3/3] Configuring environment...
set REDIS_URL=redis://localhost:6379/0
set CELERY_BROKER_URL=redis://localhost:6379/0
set CELERY_RESULT_BACKEND=redis://localhost:6379/0

echo       Environment configured!
echo.
echo ========================================================
echo   Worker is starting...
echo   Press Ctrl+C to stop
echo ========================================================
echo.

REM Start Celery worker
celery -A backend.workers.celery_config:celery_app worker --loglevel=info --concurrency=2 --pool=solo

pause
