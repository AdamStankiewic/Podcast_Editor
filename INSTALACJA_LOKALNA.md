# Instalacja Lokalna (Bez Dockera)

Instrukcja konfiguracji aplikacji do działania **całkowicie lokalnie na Windows** bez Dockera.

## Dlaczego Lokalna Instalacja?

Azure Speech SDK ma problemy z kompatybilnością z Dockerem na Windows. Uruchomienie workera lokalnie rozwiązuje te problemy.

---

## Szybki Start

### 1. Zainstaluj Redis w WSL

```powershell
wsl
sudo apt update && sudo apt install redis-server
exit
```

### 2. Zainstaluj Zależności Python

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Utwórz Plik .env

Skopiuj `.env.example` do `.env` i uzupełnij:
```env
SPEECH_KEY=twoj_klucz_azure
SPEECH_REGION=twoj_region
OPENAI_API_KEY=twoj_klucz_openai
REDIS_URL=redis://localhost:6379/0
```

### 4. Sprawdź Konfigurację

```powershell
.\setup_local.bat
```

### 5. Uruchom Wszystko

```powershell
.\start_all_local.bat
```

To otworzy 3 okna terminala:
- **Redis** - Baza danych
- **Backend** - Serwer API (http://localhost:8000)
- **Worker** - Przetwarzanie wideo

---

## Użytkowanie

1. Otwórz w przeglądarce: **http://localhost:8000**
2. Wklej URL filmu YouTube (po niemiecku)
3. Kliknij "Start Processing"
4. Czekaj na zakończenie (~3-10 minut)
5. Pobierz przekonwertowany film

---

## Nowe Funkcje

### Cache Wideo
- Filmy są zapisywane po pierwszym pobraniu
- Kolejne przetwarzanie tego samego filmu: ~30 sekund zamiast 3-5 minut
- Lokalizacja: `./data/_cache/videos/`

### Historia URL
- Śledzenie które linki były już przetwarzane
- Ostrzeżenia przy duplikatach
- Podgląd: `GET /api/history`

---

## Rozwiązywanie Problemów

### Redis się nie uruchamia

**WSL:**
```powershell
wsl
sudo service redis-server start
redis-cli ping
exit
```

### Worker pokazuje timeout

- Sprawdź połączenie internetowe
- Zweryfikuj klucze Azure w .env
- Worker ma automatyczne ponawianie (5 prób)

### Muzyka w tle za głośna

Zmień w `backend/services/render.py`:
```python
# Aktualne: -24dB, weight 0.15
# Ciszej: -30dB, weight 0.10
```

---

## Zatrzymywanie

**Szybkie:**
Zamknij okna terminali

**Czyste:**
```powershell
wsl redis-cli shutdown  # Redis
Ctrl+C                   # Backend i Worker
```

---

## Wsparcie

Szczegółowa instrukcja po angielsku: [LOCAL_SETUP.md](LOCAL_SETUP.md)
