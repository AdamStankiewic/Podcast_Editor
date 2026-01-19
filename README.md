# 🎙️ Podcast Language Converter

**Automatyczne przerabianie niemieckich podcastów z YouTube na polskie wersje z AI**

System automatycznie pobiera niemieckie filmy z YouTube, tłumaczy transkrypcję na polski, generuje profesjonalny lektor głosowy (Azure TTS) i tworzy finalne wideo z polską narracją, muzyką w tle i overlay'em.

---

## 🎯 Funkcjonalności

### Pipeline przetwarzania (7 kroków):

1. **📥 Pobieranie wideo** - YouTube download przez yt-dlp
2. **📝 Transkrypcja** - Automatyczne pobieranie napisów DE z YouTube (fallback: wklejenie ręczne)
3. **🔄 Tłumaczenie** - OpenAI GPT-4 z zachowaniem kontekstu, stylu i długości tekstu
4. **🗣️ Fonetyka** - Wstrzykiwanie SSML tags (`<sub>`, `<phoneme>`) z `pronunciations.csv`
5. **🎤 Synteza mowy** - Azure TTS Neural Voice (Ollie) z batch processing
6. **🎬 Montaż wideo** - ffmpeg: speed adjustment, audio ducking, overlay, muzyka
7. **✅ Export** - Finalne MP4 z polskim lektorem

### Kluczowe cechy:

- ✅ **Idempotentne kroki** - Wznawianie po błędach, pomijanie ukończonych kroków
- ✅ **Kolejka zadań** - Celery + Redis dla wielowątkowego przetwarzania
- ✅ **Live monitoring** - WebSocket streaming logów, progress bar
- ✅ **REST API** - FastAPI z pełną dokumentacją (Swagger)
- ✅ **Web UI** - Prosty interfejs HTMX do zarządzania kolejką

---

## 🚀 Szybki start (Docker)

### 1. Klonowanie repo

```bash
git clone <repository-url>
cd Podcast_Rditor
```

### 2. Konfiguracja środowiska

Skopiuj plik `.env.example` do `.env` i wypełnij klucze API:

```bash
cp .env.example .env
nano .env
```

**Wymagane klucze:**

```env
# Azure TTS
SPEECH_KEY=your_azure_speech_key
SPEECH_REGION=northeurope

# OpenAI (do tłumaczenia)
OPENAI_API_KEY=your_openai_key
```

### 3. Setup assets

Wygeneruj placeholder assets:

```bash
python3 setup_assets.py
```

**Opcjonalnie:** Zamień na własne:
- `assets/overlay.png` - Ramka PNG z alpha channel (1920x1080)
- `assets/loop.wav` - Muzyka w tle (będzie zapętlona)
- `pronunciations.csv` - Reguły wymowy (np. Wehrmacht → wermacht)

### 4. Uruchomienie

```bash
docker-compose up -d
```

Aplikacja dostępna: **http://localhost:8000**

---

## 📖 Użytkowanie

### Web UI

1. Otwórz http://localhost:8000
2. Wklej linki YouTube (jeden na linię)
3. Kliknij **🚀 Start Processing**
4. Monitoruj postęp w tabeli
5. Pobierz finalne MP4 gdy status = **DONE**

### API (cURL)

**Stwórz zadanie:**

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "https://www.youtube.com/watch?v=xxxxx",
      "https://youtu.be/yyyyy"
    ]
  }'
```

**Lista zadań:**

```bash
curl http://localhost:8000/api/jobs
```

**Status zadania:**

```bash
curl http://localhost:8000/api/jobs/{job_id}
```

**Pobierz finalne wideo:**

```bash
curl -O http://localhost:8000/api/jobs/{job_id}/download
```

---

## 🏗️ Architektura

### Nowa architektura v2.0 (Sequential Language Tasks)

System został przeprojektowany z monolitycznego taska na **orchestrator + osobne taski per język**:

**Dlaczego?**
- GPU safety: Resemble Enhance + NVENC rendering nie mogą działać równolegle (OOM)
- Dynamiczne limity: Każdy język ma limit dopasowany do długości filmu
- Partial success: Jeśli FR failuje, PL i EN już gotowe (nie tracisz 8h pracy)
- Łatwiejszy retry: Możesz przetwarzać tylko failed języki

**Pipeline:**
```
┌─────────────────────────────────────┐
│ process_podcast (orchestrator)      │
│ ├─ Download video (shared)          │
│ └─ Get transcript (shared)          │
└─────────────────────────────────────┘
              ↓ sequential
┌─────────────────────────────────────┐
│ process_language("pl", duration)    │
│ ├─ Translate → TTS → Enhance → Render│
│ └─ Dynamic limit (auto-calculated)  │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ process_language("fr", duration)    │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ process_language("en", duration)    │
└─────────────────────────────────────┘
```

**Struktura plików:**

```
📦 Podcast_Rditor
├── backend/
│   ├── app.py                     # FastAPI application
│   ├── models.py                  # Pydantic models (Job, Progress, PARTIAL_SUCCESS)
│   ├── pipeline/                  # Pipeline steps
│   │   ├── download.py            # Step 1: YouTube download
│   │   ├── transcribe.py          # Step 2: Get German transcript
│   │   ├── translate_step.py      # Step 3: DE → PL translation
│   │   ├── tts_step.py            # Step 4: Generate SSML + TTS
│   │   └── render_step.py         # Step 5: Video rendering
│   ├── services/
│   │   ├── storage.py             # Artifact management + idempotency
│   │   ├── youtube.py             # yt-dlp wrapper
│   │   ├── translate.py           # OpenAI translation with chunking
│   │   ├── phonetics.py           # CSV parser + SSML injection
│   │   ├── azure_tts_batch.py     # Azure TTS batch synthesis
│   │   └── render.py              # ffmpeg video processing
│   └── workers/
│       ├── celery_config.py       # Celery configuration (global defaults)
│       └── tasks.py               # Orchestrator + language tasks with dynamic limits
├── frontend/
│   ├── templates/index.html       # Web UI (HTMX)
│   └── static/style.css
├── tests/
│   ├── test_phonetics.py          # Phonetics unit tests
│   └── test_idempotency.py        # Idempotency tests
├── assets/
│   ├── overlay.png                # Video overlay frame
│   ├── loop.wav                   # Background music
│   └── .gitkeep
├── pronunciations.csv             # Pronunciation rules
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 🔧 Konfiguracja zaawansowana

### Zmienne środowiskowe (.env)

```env
# Azure TTS
SPEECH_KEY=xxx
SPEECH_REGION=northeurope
TTS_VOICE=en-GB-Ollie:DragonHDLatestNeural
TTS_RATE=-8%
TTS_PITCH=0%

# OpenAI
OPENAI_API_KEY=xxx
OPENAI_MODEL=gpt-4o-mini

# Redis
REDIS_URL=redis://localhost:6379/0

# Storage
STORAGE_PATH=./data
OUTPUT_PATH=./output

# Assets
OVERLAY_PATH=./assets/overlay.png
LOOP_AUDIO_PATH=./assets/loop.wav
PRONUNCIATIONS_CSV=./pronunciations.csv

# Limits
MAX_VIDEO_DURATION_HOURS=2
```

### Fonetyka (pronunciations.csv)

Format: `source,target,mode`

**Tryby:**
- `sub` - Podstawienie (alias): `Wehrmacht → wermacht`
- `phoneme_ipa` - IPA notation: `Führer → ˈfyːʁɐ`

**Przykład:**

```csv
source,target,mode
Wehrmacht,wermacht,sub
Führer,fiurer,sub
München,minchen,sub
Test,tɛst,phoneme_ipa
```

**Zasady:**
- Case-insensitive matching (wehrmacht = WEHRMACHT)
- Whole-word only (Wehrmacht ✅, Wehrmachtssoldat ❌)
- Sortowanie: najdłuższe frazy pierwsze

---

## 🎬 Montaż wideo (ffmpeg)

### Pipeline renderowania:

1. **Analiza** - Oblicza długości video/audio
2. **Speed adjustment** - Dopasowuje prędkość wideo do audio (0.5x - 2.0x)
3. **Muzyka** - Zapętla `loop.wav` do długości audio
4. **Ducking** - Sidechain compression (muzyka cichnie pod głosem):
   ```
   threshold=0.02:ratio=6:attack=5ms:release=250ms
   ```
5. **Overlay** - Nakłada `overlay.png` z alpha channel
6. **Export** - H.264 + AAC, 192kbps audio

### Ręczny render (bez systemu):

```bash
# Przykład: Zamień audio + overlay
ffmpeg -i original.mp4 -i polish_audio.wav -i overlay.png \
  -filter_complex "[0:v]setpts=0.95*PTS[v];[v][2:v]overlay=0:0[vout]" \
  -map "[vout]" -map 1:a \
  -c:v libx264 -c:a aac -b:a 192k \
  final.mp4
```

---

## 🧪 Testy

### Uruchomienie testów:

```bash
# Wszystkie testy
pytest

# Z coverage
pytest --cov=backend tests/

# Konkretny plik
pytest tests/test_phonetics.py -v
```

### Testy obejmują:

- ✅ Phonetics CSV parser
- ✅ SSML injection (case-insensitive, whole-word)
- ✅ SSML validation (mismatched tags)
- ✅ Storage idempotency
- ✅ Artifact existence checks
- ✅ Concurrent access scenarios

---

## 📊 Monitoring i Debugging

### Logs

**Job logs (WebSocket streaming):**
```javascript
// Frontend auto-connects to ws://localhost:8000/ws
```

**Pliki logów:**
```
data/{job_id}/
├── job_state.json      # Stan zadania
├── pipeline.log        # Szczegółowe logi
└── artifacts/          # Pośrednie pliki
```

**Celery logs:**
```bash
docker-compose logs -f worker
```

### Health check

```bash
curl http://localhost:8000/health
```

### Debug mode

```bash
# Backend z hot-reload
uvicorn backend.app:app --reload --log-level debug

# Worker z debug
celery -A backend.workers.celery_config:celery_app worker --loglevel=debug
```

---

## 🐛 Troubleshooting

### Problem: Azure TTS timeout

**Rozwiązanie:**
1. Zmień region na bliższy: `SPEECH_REGION=germanywestcentral`
2. Zmniejsz chunk size w `azure_tts_batch.py`: `max_chars = 2000`
3. Zwiększ retry: `max_retries = 10`

### Problem: Translation hallucinations (dodawanie faktów)

**Rozwiązanie:**
1. Użyj DeepL zamiast OpenAI (wymaga API key)
2. Zwiększ `temperature=0.2` w `translate.py`
3. Dodaj post-processing validation

### Problem: Video/audio desync

**Rozwiązanie:**
1. Sprawdź stosunek długości: `ffprobe original.mp4` vs `ffprobe tts.wav`
2. Jeśli ratio > 2.0x, zwiększ dopuszczalny zakres w `render.py`
3. Alternatywnie: dopasuj TTS rate dynamicznie

### Problem: Overlay nie widoczny

**Rozwiązanie:**
1. Sprawdź czy `overlay.png` ma alpha channel: `ffprobe overlay.png`
2. Upewnij się, że rozdzielczość = video (1920x1080)
3. Testuj ręcznie: `ffmpeg -i video.mp4 -i overlay.png -filter_complex "overlay=0:0" test.mp4`

### Problem: SoftTimeLimitExceeded dla długich filmów

**Objawy:** Zadanie kończy się błędem "SoftTimeLimitExceeded()" podczas przetwarzania

**Przyczyna:** System używa **dynamicznych limitów czasu** per język, obliczanych automatycznie na podstawie długości filmu

**Jak to działa (Nowa architektura v2.0):**
1. Każdy język jest przetwarzany jako osobny task z własnymi limitami
2. Limity obliczane dynamicznie: `base_time (40 min) + enhance_time + render_time`
3. Sequential execution (PL → FR → EN) chroni GPU przed przeciążeniem
4. **Partial Success**: Jeśli jeden język failuje, inne kontynuują

**Wzór obliczania limitów:**
```python
base_time = 40 min  # Translation + TTS (stałe)
enhance_time = min(video_duration * 0.25, 40 min)  # Resemble Enhance
render_time = video_duration * 1.5  # FFmpeg NVENC @ 3.4x speed
total_limit = (base_time + enhance_time + render_time) * 1.2  # +20% margin
```

**Szacunkowy czas przetwarzania per język:**
- Film 10 min: ~58 min
- Film 1h: ~2.4h
- Film 2h: ~4.2h
- Film 3h: ~6.3h

**Całkowity czas dla 3 języków (sequential):**
- Film 1h: ~7.2h
- Film 2h: ~12.6h
- Film 3h: ~19h

**Rozwiązywanie problemów:**
- Limity ustawiane automatycznie - **nie trzeba ręcznie edytować**
- Jeśli task timeout, sprawdź logi GPU (może być throttling)
- Dla filmów 3h+ upewnij się że masz wystarczająco RAM/GPU memory

---

## 🚢 Deployment (Production)

### Docker Compose Production

```yaml
# docker-compose.prod.yml
services:
  backend:
    restart: always
    environment:
      - WORKERS=4
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

  worker:
    restart: always
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '4'
          memory: 8G
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name podcast.example.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://localhost:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Systemd Service (bez Docker)

```ini
# /etc/systemd/system/podcast-converter.service
[Unit]
Description=Podcast Language Converter
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/podcast-converter
Environment="PATH=/opt/podcast-converter/venv/bin"
ExecStart=/opt/podcast-converter/venv/bin/uvicorn backend.app:app --host 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 📈 Performance & Optymalizacja

### Typowe czasy przetwarzania (10-minutowy podcast):

| Krok | Czas | Uwagi |
|------|------|-------|
| Download | 30s - 2min | Zależy od prędkości internetu |
| Transcribe | 5s | Jeśli napisy dostępne na YT |
| Translate | 1-3min | ~2000 znaków/min (GPT-4o-mini) |
| TTS | 3-5min | Azure batch + chunking |
| Render | 2-4min | ffmpeg encoding |
| **TOTAL** | **~10-15min** | Dla 10-min video |

**Uwaga:** System używa **dynamicznych limitów czasu** per język. Dla długich filmów (2+ godziny) z 3 językami, całkowity czas może wynosić 12-19 godzin (sequential execution chroni GPU). Każdy język ma własny task z automatycznie obliczonym limitem.

### Optymalizacje:

**GPU Acceleration (NVENC):**
```env
# .env - Enabled by default
USE_GPU_ENCODING=true  # 8x faster video rendering (NVIDIA/AMD)
```

**RAM Disk (Optional - 20% faster I/O):**
```env
# .env - For 32GB+ RAM systems
TEMP_PATH=R:/podcast_temp  # Use RAM Disk for temp files

# Setup: See docs/RAMDISK_SETUP.md
# Requires: ImDisk Toolkit (Windows) or similar
# Benefits: 20x faster temp file I/O, reduces SSD wear
```

**Faster translation:**
```python
# translate.py - użyj mniejszego modelu
OPENAI_MODEL = "gpt-3.5-turbo"  # 2x szybszy
```

**Parallel processing:**
```yaml
# docker-compose.yml - więcej workerów
worker:
  deploy:
    replicas: 4
```

---

## 🤝 Contributing

### Development setup

```bash
# Virtual env
python -m venv venv
source venv/bin/activate

# Install deps
pip install -r requirements.txt

# Pre-commit hooks
pip install pre-commit
pre-commit install
```

### Code style

```bash
# Format
black backend/ tests/

# Lint
flake8 backend/ tests/

# Type check
mypy backend/
```

---

## 📝 License

MIT License - see LICENSE file

---

## 🙏 Credits

**Tech Stack:**
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [Celery](https://docs.celeryq.dev/) - Task queue
- [Azure TTS](https://azure.microsoft.com/en-us/products/ai-services/text-to-speech) - Neural voice synthesis
- [OpenAI GPT](https://openai.com/api/) - Translation
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - YouTube download
- [FFmpeg](https://ffmpeg.org/) - Video processing
- [HTMX](https://htmx.org/) - Frontend interactivity

**Author:** Senior Full-Stack Engineer
**Version:** 1.0.0 MVP
**Date:** 2025-01-10

---

## 📞 Support

**Issues:** [GitHub Issues](https://github.com/your-repo/issues)
**Docs:** [Full Documentation](https://docs.example.com)
**Email:** support@example.com

---

**Enjoy automated podcast language conversion! 🎙️🇩🇪→🇵🇱**
