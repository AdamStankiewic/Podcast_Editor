@echo off
REM ========================================================
REM Start Redis Locally (WSL)
REM ========================================================

echo Starting Redis on WSL...
wsl redis-server --daemonize yes --port 6379 --bind 127.0.0.1

timeout /t 2 /nobreak >nul

wsl redis-cli ping >nul 2>&1
if errorlevel 1 (
    echo ERROR: Redis failed to start!
    pause
    exit /b 1
)

echo ✓ Redis is running on localhost:6379
echo.
echo To stop Redis: wsl redis-cli shutdown
echo.
