@echo off
REM ========================================================
REM Start only Redis and Backend in Docker
REM (Worker will run locally on Windows)
REM ========================================================

echo.
echo ========================================================
echo   Starting Redis + Backend (Docker)
echo   Worker will run locally for Azure TTS compatibility
echo ========================================================
echo.

REM Stop all services first
echo [1/3] Stopping all Docker containers...
docker compose down
echo       Done!

REM Start only Redis and Backend
echo [2/3] Starting Redis and Backend...
docker compose up redis backend -d
echo       Done!

REM Wait for services to be healthy
echo [3/3] Waiting for services to be ready...
timeout /t 5 /nobreak >nul
echo       Done!

echo.
echo ========================================================
echo   STATUS:
echo   - Redis:   Running on localhost:6379
echo   - Backend: Running on http://localhost:8000
echo   - Worker:  NOT RUNNING (run locally with run_worker_local.bat)
echo ========================================================
echo.
echo Next steps:
echo   1. Open a new PowerShell window
echo   2. Run: .\run_worker_local.bat
echo   3. Open browser: http://localhost:8000
echo.

pause
