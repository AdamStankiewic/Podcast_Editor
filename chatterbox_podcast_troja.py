# chatterbox_podcast_troja.py
# Uruchom: python chatterbox_podcast_troja.py
#
# Pipeline: Phonetics → Chatterbox TTS → ffmpeg → Resemble Enhance (opcjonalnie)

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
import torch
import torchaudio as ta
import subprocess
import os
import sys
import pathlib
import platform

# Fix PosixPath on Windows (for Resemble Enhance model loading)
if platform.system() == "Windows":
    pathlib.PosixPath = pathlib.WindowsPath

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.services.phonetics import PhoneticsService

# =============================================
# KONFIGURACJA
# =============================================
EXAGGERATION  = 1.05      # 1.0-1.15 – wyraźniejsza intonacja
CFG_WEIGHT    = 0.45      # nisko – więcej swobody
TEMPERATURE   = 0.98      # wysoko – różnorodność prozodii
SLOW_FACTOR   = 0.96      # delikatne przyspieszenie (prawie surowe tempo)
LOUDNESS      = -17       # lekko głośniej niż -18
LRA           = 11        # wysoko → zachowuje dynamikę

# Resemble Enhance
ENABLE_ENHANCE = True     # True = użyj Resemble Enhance na końcu
ENHANCE_NFE    = 64       # 32=szybki, 64=średni, 128=max jakość

RAW_FILE      = 'troja_dluzszy_raw.wav'
OUTPUT_FILE   = 'troja_dluzszy_zywszy_podcast.wav'
ENHANCED_FILE = 'troja_dluzszy_enhanced.wav'

# Dłuższy tekst – historia Troi + Iliada
paragraphs = [
    'Troja była miastem położonym w północno-zachodniej Anatolii, w pobliżu cieśniny Dardanele. Ta strategiczna lokalizacja uczyniła ją przez długi czas ważnym miejscem na mapie starożytnego świata.',
    'To tutaj krzyżowały się szlaki handlowe, które łączyły Europę z Azją. Miasto było punktem styku pomiędzy światem nadmorskim a lądowym.',
    'Troja nie była zwykłą osadą. Było to miejsce, w którym koncentrowały się handel, władza i konflikty. Z biegiem lat zyskała status jednego z najbardziej znanych miejsc w mitologii starożytnej.',
    'Według tradycji, Troja została założona przez Ilosa, syna Troosa, od którego pochodzi nazwa miasta – Ilion. Miasto rozwijało się przez wieki, osiągając szczyt potęgi w epoce brązu.',
    'Najbardziej znana jest jednak dzięki wojnie trojańskiej, opisanej przez Homera w Iliadzie. Według mitu, wszystko zaczęło się od jabłka niezgody i porwania Heleny przez Parysa.',
    'Dziesięć lat trwało oblężenie Troi przez Greków. Achilles, Hektor, Odyseusz – to postacie, które na zawsze wryły się w pamięć ludzkości.',
    'Ostatecznie Troja padła nie przez siłę oręża, lecz podstęp – drewniany koń, w którym ukryli się wojownicy. Po zdobyciu miasta Grecy spalili je doszczętnie.',
    'Przez wieki uważano, że Troja to tylko mit. Dopiero w XIX wieku Heinrich Schliemann rozpoczął wykopaliska w Hisarlık i odkrył warstwy archeologiczne potwierdzające istnienie potężnego miasta w tym miejscu.',
    'Dziś Troja jest wpisana na listę światowego dziedzictwa UNESCO i przypomina nam, jak cienka jest granica między mitem a historią.'
]

# =============================================
# KROK 1: Wymowa — zamień nazwy własne na fonetyczne
# =============================================
print('Ładowanie reguł wymowy...')
phonetics = PhoneticsService(csv_path='./pronunciations.csv')

processed_paragraphs = []
for i, text in enumerate(paragraphs):
    fixed, count = phonetics.apply_text_replacements(text)
    if count > 0:
        print(f'  Akapit {i+1}: {count} zamian wymowy')
    processed_paragraphs.append(fixed)

# =============================================
# KROK 2: Generowanie TTS (Chatterbox)
# =============================================
print('Ładowanie modelu Chatterbox...')
model = ChatterboxMultilingualTTS.from_pretrained(device='cuda')
print('Model załadowany.')

audio_chunks = []
for i, text in enumerate(processed_paragraphs):
    print(f'Generuję akapit {i+1}/{len(processed_paragraphs)}...')
    kwargs = {
        'text': text,
        'audio_prompt_path': 'assets/voice_reference.wav',
        'language_id': 'pl',
        'exaggeration': EXAGGERATION,
        'cfg_weight': CFG_WEIGHT,
    }
    try:
        kwargs['temperature'] = TEMPERATURE
    except TypeError:
        print("Uwaga: temperature nieobsługiwane w tej wersji – pomijam")

    wav = model.generate(**kwargs)
    audio_chunks.append(wav)

# Sklej chunki
if len(audio_chunks) > 1:
    full_wav = torch.cat(audio_chunks, dim=1)
else:
    full_wav = audio_chunks[0]

ta.save(RAW_FILE, full_wav, model.sr)
print(f'Zapisano surowy plik: {RAW_FILE}')

# =============================================
# KROK 3: ffmpeg – minimalna obróbka
# =============================================
print('Przetwarzam ffmpeg – minimalna obróbka...')
subprocess.run([
    'ffmpeg', '-y',
    '-i', RAW_FILE,
    '-af', f'atempo={SLOW_FACTOR},afftdn=nf=-30,volume=2.5dB',
    '-ar', '48000',
    OUTPUT_FILE
], check=True)
print(f'Zapisano po ffmpeg: {OUTPUT_FILE}')

# =============================================
# KROK 4: Resemble Enhance (opcjonalnie)
# =============================================
if ENABLE_ENHANCE:
    try:
        from resemble_enhance.enhancer.inference import enhance

        print(f'Resemble Enhance (nfe={ENHANCE_NFE})...')
        dwav, sr = ta.load(OUTPUT_FILE)
        dwav = dwav.squeeze(0) if dwav.shape[0] == 1 else torch.mean(dwav, dim=0)

        enhanced, new_sr = enhance(
            dwav, sr, 'cuda',
            nfe=ENHANCE_NFE,
            solver='midpoint',
            lambd=0.9,
            tau=0.5
        )

        if enhanced.dim() == 1:
            enhanced = enhanced.unsqueeze(0)
        ta.save(ENHANCED_FILE, enhanced.cpu(), new_sr)
        print(f'Zapisano po Resemble Enhance: {ENHANCED_FILE}')

    except ImportError:
        print('Resemble Enhance niedostępny – pomijam. Uruchom: python scripts/patch_resemble_enhance.py')
    except Exception as e:
        print(f'Resemble Enhance błąd: {e} – pomijam')

# =============================================
# PODSUMOWANIE
# =============================================
print()
print('Gotowe! Pliki:')
print(f'  Surowy TTS:        {os.path.abspath(RAW_FILE)}')
print(f'  Po ffmpeg:         {os.path.abspath(OUTPUT_FILE)}')
if ENABLE_ENHANCE and os.path.exists(ENHANCED_FILE):
    print(f'  Po Enhance:        {os.path.abspath(ENHANCED_FILE)}')
