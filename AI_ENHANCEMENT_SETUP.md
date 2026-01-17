# AI Audio Enhancement Setup

## 🎯 Resemble Enhance - AI Voice Enhancement (RECOMMENDED)

Resemble Enhance to AI model który zamienia syntetyczny głos TTS na ultra-naturalny. Najlepsza opcja dla Twojego projektu.

### Wymagania:
- Python 3.8+
- NVIDIA GPU z CUDA support (dla przyspieszenia ~5x)
- ~4GB miejsca na dysku (modele AI)

### Instalacja (Windows z CUDA):

```bash
# 1. Aktywuj venv
cd C:\Users\adams\Desktop\Podcast_Editor
.venv\Scripts\activate

# 2. Zainstaluj PyTorch z CUDA 12.1 support
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 3. Zainstaluj Resemble Enhance
pip install resemble-enhance

# 4. Sprawdź czy działa
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"
```

### Parametry w kodzie:

Możesz dostosować jakość vs szybkość w `/backend/services/audio_postprocessing.py`:

```python
nfe=64  # Number of function evaluations
# 32 = szybkie (~10s per plik)
# 64 = balanced (~20s per plik) ✓ DOMYŚLNE
# 128 = najlepsza jakość (~40s per plik)

tau=0.5  # Denoising strength
# 0.3 = lekkie czyszczenie
# 0.5 = balanced ✓ DOMYŚLNE
# 0.7 = mocne czyszczenie (może brzmieć "processed")
```

## 🔊 Co Resemble Enhance robi:

1. **Denoising** - Usuwa szumy tła (lepiej niż FFmpeg)
2. **Voice Enhancement** - Dodaje ciepło, wyrazistość, naturalność
3. **Super-resolution** - Upscaling audio (48kHz → "studio quality")
4. **Artifact removal** - Usuwa artefakty TTS (robotic voice, clicks)

## 📊 Pipeline po instalacji:

```
TTS (Azure)
  ↓
Pre-conversion (mono 48kHz)
  ↓
✨ Resemble Enhance (AI enhancement) ✨  ← NOWE
  ↓
Studio Chain (EQ, Compression)
  ↓
LUFS Normalization (-16 LUFS)
  ↓
Final Audio (tts_studio.wav)
```

## 🧪 Test przed pełnym użyciem:

Po instalacji, możesz przetestować na jednym pliku:

```bash
cd C:\Users\adams\Desktop\Podcast_Editor

# Znajdź ostatni job ID
dir data

# Test enhancement
python -c "
from pathlib import Path
from backend.services.audio_postprocessing import get_audio_postprocessing

job_id = 'TWOJ_JOB_ID'  # Wpisz ostatni job ID
input_wav = Path(f'data/{job_id}/tts.wav')
output_wav = Path(f'data/{job_id}/tts_test_enhanced.wav')

pp = get_audio_postprocessing(enable_ai_enhance=True)
pp.process_audio(input_wav, output_wav)
print(f'Test complete! Compare:')
print(f'Original: {input_wav}')
print(f'Enhanced: {output_wav}')
"
```

Następnie porównaj oba pliki w VLC - różnica powinna być ogromna!

## ⚠️ Troubleshooting:

### CUDA not available:
```bash
# Sprawdź wersję CUDA
nvidia-smi

# Jeśli masz CUDA 11.8, użyj:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

### Out of memory (GPU):
Zmniejsz `nfe` w kodzie z 64 na 32.

### Zbyt wolne (CPU mode):
Jeśli nie masz GPU, zmniejsz `nfe` z 64 na 32 i użyj `solver="euler"` zamiast `"midpoint"`.

## 🎛️ Alternatywa: DeepFilterNet (tylko noise reduction)

Jeśli Resemble Enhance jest zbyt ciężki, możesz użyć lżejszego DeepFilterNet (tylko noise reduction):

```bash
pip install deepfilternet
```

Pipeline automatycznie użyje tego co jest dostępne:
1. Resemble Enhance (jeśli zainstalowany) ✓ NAJLEPSZE
2. DeepFilterNet (jeśli zainstalowany)
3. FFmpeg filters only (fallback)

## ✅ Po instalacji:

1. Zrestartuj Celery worker
2. Uruchom nowy job (poprzednie są cache'owane)
3. Sprawdź logi - powinno być: `✓ Resemble Enhance available (AI voice enhancement with GPU)`
4. Porównaj `tts.wav` vs `tts_studio.wav` - różnica powinna być OGROMNA

## 📈 Oczekiwane rezultaty:

**Przed (tts.wav):**
- Syntetyczny głos
- Brak ciepła
- Artefakty TTS
- Płaskie brzmienie

**Po (tts_studio.wav):**
- Naturalny, ludzki głos
- Ciepłe brzmienie
- Bez artefaktów
- Studyjne brzmienie
- Wyrazistość i obecność

Powodzenia! 🚀
