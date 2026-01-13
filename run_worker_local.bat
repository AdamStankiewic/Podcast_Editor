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
REM   4. .env file with credentials in project root
REM ========================================================

echo.
echo ========================================================
echo   Starting Celery Worker Locally (Azure TTS Fix)
echo ========================================================
echo.

REM Check if Redis is running
echo [1/4] Checking Redis connection...
docker ps | findstr podcast_redis >nul
if errorlevel 1 (
    echo ERROR: Redis container is not running!
    echo Please start it with: docker compose up redis backend -d
    pause
    exit /b 1
)
echo       Redis is running!

REM Check if dependencies are installed
echo [2/4] Checking Azure Speech SDK...
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

REM Load environment variables from .env file
echo [3/4] Loading environment variables from .env...
if not exist .env (
    echo ERROR: .env file not found!
    echo Please create .env file with your credentials
    pause
    exit /b 1
)

REM Parse .env file and set environment variables
for /f "usebackq tokens=1,* delims==" %%a in (.env) do (
    REM Skip comments and empty lines
    echo %%a | findstr /r "^#" >nul
    if errorlevel 1 (
        if not "%%a"=="" (
            set "%%a=%%b"
        )
    )
)

REM Set Celery-specific environment variables
set REDIS_URL=redis://localhost:6379/0
set CELERY_BROKER_URL=redis://localhost:6379/0
set CELERY_RESULT_BACKEND=redis://localhost:6379/0

echo       Environment variables loaded!

REM Verify critical env vars are set
echo [4/4] Verifying credentials...
if "%SPEECH_KEY%"=="" (
    echo ERROR: SPEECH_KEY not found in .env file!
    pause
    exit /b 1
)
if "%SPEECH_REGION%"=="" (
    echo ERROR: SPEECH_REGION not found in .env file!
    pause
    exit /b 1
)
echo       SPEECH_KEY: ********%SPEECH_KEY:~-4%
echo       SPEECH_REGION: %SPEECH_REGION%
echo.
echo ========================================================
echo   Worker is starting...
echo   Press Ctrl+C to stop
echo ========================================================
echo.

REM Start Celery worker
celery -A backend.workers.celery_config:celery_app worker --loglevel=info --concurrency=2 --pool=solo

pause
