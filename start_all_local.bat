@echo off
REM ========================================================
REM Start All Services Locally (No Docker)
REM ========================================================
REM Opens 3 terminal windows for Redis, Backend, Worker
REM ========================================================

echo.
echo ========================================================
echo   Starting All Services Locally (No Docker)
echo ========================================================
echo.
echo This will open 3 terminal windows:
echo   1. Redis (WSL)
echo   2. Backend (FastAPI on port 8000)
echo   3. Worker (Celery)
echo.
echo Press any key to continue...
pause >nul

REM Start Redis in new window
echo Starting Redis...
start "Redis (WSL)" cmd /k "start_redis_local.bat"
timeout /t 3 /nobreak >nul

REM Start Backend in new window
echo Starting Backend...
start "Backend (FastAPI)" cmd /k "start_backend_local.bat"
timeout /t 3 /nobreak >nul

REM Start Worker in new window
echo Starting Worker...
start "Worker (Celery)" cmd /k "start_worker_local.bat"

echo.
echo ========================================================
echo   All Services Starting!
echo ========================================================
echo.
echo Redis:   Check "Redis (WSL)" window
echo Backend: http://localhost:8000
echo Worker:  Check "Worker (Celery)" window
echo.
echo Close the terminal windows to stop services
echo.
pause
