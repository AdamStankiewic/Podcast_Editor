@echo off
REM ===================================================================
REM  Podcast Editor - Auto Start Script
REM  Uruchamia Redis, Celery Worker i Web Server w WSL
REM ===================================================================

echo.
echo ========================================
echo   Podcast Editor - Starting...
echo ========================================
echo.

REM Sprawdz czy WSL jest zainstalowany
wsl --list >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: WSL nie jest zainstalowany!
    echo Zainstaluj WSL: wsl --install
    pause
    exit /b 1
)

echo [1/4] Sprawdzam Redis...
wsl bash -c "sudo service redis-server status | grep -q 'is running' || sudo service redis-server start"
if %errorlevel% equ 0 (
    echo       ✓ Redis dziala
) else (
    echo       ✓ Redis uruchomiony
)

echo.
echo [2/4] Uruchamiam Celery Worker (1 job na raz - nie przeciazy kompa)...
start "Celery Worker" wsl bash -c "cd /mnt/c/Users/adams/Desktop/Podcast_Editor && source .venv/bin/activate && celery -A backend.celery_app worker --loglevel=info --concurrency=1"
timeout /t 3 >nul
echo       ✓ Celery Worker started (concurrency=1)

echo.
echo [3/4] Instaluje brakujace pakiety (jesli potrzebne)...
wsl bash -c "cd /mnt/c/Users/adams/Desktop/Podcast_Editor && source .venv/bin/activate && pip install -q fastapi uvicorn celery redis python-dotenv azure-cognitiveservices-speech openai pydantic pydantic-settings httpx python-dateutil python-multipart jinja2 websockets 2>&1 | grep -v 'already satisfied' || echo 'Wszystkie pakiety zainstalowane'"
echo       ✓ Pakiety sprawdzone

echo.
echo [4/4] Uruchamiam Web Server...
echo.
echo ========================================
echo   ✓ Podcast Editor gotowy!
echo ========================================
echo.
echo   Web UI:     http://localhost:8000
echo   Dokumentacja: http://localhost:8000/docs
echo.
echo   Aby zatrzymac: Zamknij to okno lub nacisnij Ctrl+C
echo.
echo ========================================
echo.

REM Otworz przegladarke po 5 sekundach
start "" timeout /t 5 /nobreak >nul && start http://localhost:8000

REM Uruchom server (blocking - trzyma okno otwarte)
wsl bash -c "cd /mnt/c/Users/adams/Desktop/Podcast_Editor && source .venv/bin/activate && python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000"

REM Cleanup gdy zamknieto
echo.
echo Zamykanie...
wsl bash -c "pkill -f celery" 2>nul
echo Celery Worker zatrzymany
pause
