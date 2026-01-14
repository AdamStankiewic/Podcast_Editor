@echo off
REM ========================================================
REM Start Backend Locally (FastAPI + Uvicorn)
REM ========================================================

echo.
echo ========================================================
echo   Starting Backend Locally (No Docker)
echo ========================================================
echo.

REM Load environment variables
if not exist .env (
    echo ERROR: .env file not found!
    pause
    exit /b 1
)

REM Parse .env file
for /f "usebackq tokens=1,* delims==" %%a in (.env) do (
    echo %%a | findstr /r "^#" >nul
    if errorlevel 1 (
        if not "%%a"=="" (
            set "%%a=%%b"
        )
    )
)

REM Set local URLs
set REDIS_URL=redis://localhost:6379/0
set CELERY_BROKER_URL=redis://localhost:6379/0
set CELERY_RESULT_BACKEND=redis://localhost:6379/0

echo Starting FastAPI backend on http://localhost:8000
echo Press Ctrl+C to stop
echo.

REM Start Uvicorn
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
