@echo off
REM ========================================================
REM Full Local Setup - No Docker Required
REM ========================================================
REM Runs Redis, Backend, and Worker all locally on Windows
REM ========================================================

echo.
echo ========================================================
echo   Starting FULL LOCAL SETUP (No Docker)
echo ========================================================
echo.

REM Check if Redis is installed (WSL)
echo [1/3] Checking Redis (WSL)...
wsl redis-server --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ========================================================
    echo   Redis not found in WSL
    echo ========================================================
    echo.
    echo You need Redis running. Two options:
    echo.
    echo OPTION 1: Use WSL Redis (Recommended)
    echo   1. Open PowerShell and run: wsl
    echo   2. In WSL run: sudo apt update && sudo apt install redis-server
    echo   3. Start Redis: redis-server --daemonize yes
    echo   4. Exit WSL: exit
    echo   5. Run this script again
    echo.
    echo OPTION 2: Use Docker for Redis only
    echo   1. Start Docker Desktop
    echo   2. Run: docker run -d -p 6379:6379 --name podcast_redis redis:7-alpine
    echo   3. Run this script again
    echo.
    pause
    exit /b 1
)
echo       Redis available in WSL!

REM Check Python dependencies
echo [2/3] Checking Python dependencies...
python -c "import fastapi, celery, redis" >nul 2>&1
if errorlevel 1 (
    echo       Installing dependencies...
    pip install -r requirements.txt
)
echo       Python dependencies OK!

REM Check .env file
echo [3/3] Checking .env file...
if not exist .env (
    echo ERROR: .env file not found!
    pause
    exit /b 1
)
echo       .env file found!

echo.
echo ========================================================
echo   Setup Complete!
echo ========================================================
echo.
echo Next steps:
echo   1. Start Redis:    .\start_redis_local.bat
echo   2. Start Backend:  .\start_backend_local.bat
echo   3. Start Worker:   .\start_worker_local.bat
echo.
echo Or use: .\start_all_local.bat to start everything
echo.

pause
