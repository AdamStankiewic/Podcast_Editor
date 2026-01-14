@echo off
REM ========================================================
REM Start Worker Locally (No Docker)
REM ========================================================

echo.
echo ========================================================
echo   Starting Celery Worker Locally (No Docker)
echo ========================================================
echo.

REM Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    pause
    exit /b 1
)

REM Parse .env file and set environment variables
for /f "usebackq tokens=1,* delims==" %%a in (.env) do (
    echo %%a | findstr /r "^#" >nul
    if errorlevel 1 (
        if not "%%a"=="" (
            set "%%a=%%b"
        )
    )
)

REM Set local Redis URLs
set REDIS_URL=redis://localhost:6379/0
set CELERY_BROKER_URL=redis://localhost:6379/0
set CELERY_RESULT_BACKEND=redis://localhost:6379/0

REM Verify credentials
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

echo ✓ Credentials loaded
echo   SPEECH_KEY: ********%SPEECH_KEY:~-4%
echo   SPEECH_REGION: %SPEECH_REGION%
echo.
echo Starting Celery worker...
echo Press Ctrl+C to stop
echo.

REM Start Celery worker
celery -A backend.workers.celery_config:celery_app worker --loglevel=info --concurrency=2 --pool=solo
