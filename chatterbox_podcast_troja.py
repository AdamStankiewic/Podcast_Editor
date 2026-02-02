# chatterbox_podcast_troja.py
# Uruchom: python chatterbox_podcast_troja.py
# Tryb HQ: python chatterbox_podcast_troja.py --hq
#
# Pipeline: Phonetics -> Chatterbox TTS -> ffmpeg -> Resemble Enhance
#
# Generuje 4 pliki:
#   1. troja_dluzszy_raw.wav          - surowy TTS z Chatterbox
#   2. troja_dluzszy_raw_enhanced.wav - surowy TTS + Resemble Enhance (bez ffmpeg)
#   3. troja_dluzszy_podcast.wav      - po ffmpeg (tempo, odszumianie)
#   4. troja_dluzszy_enhanced.wav     - po ffmpeg + Resemble Enhance

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
# TRYB HQ (--hq flag)
# =============================================
HQ_MODE = '--hq' in sys.argv

# =============================================
# KONFIGURACJA
# =============================================
if HQ_MODE:
    print('=== TRYB HIGH QUALITY ===')
    EXAGGERATION  = 0.7       # spokojniejszy, naturalniejszy narrator
    CFG_WEIGHT    = 0.55      # troche wiecej wiernosci tekstowi
    TEMPERATURE   = 0.92      # mniej losowosci = stabilniejszy glos
    SLOW_FACTOR   = 0.94      # delikatnie wolniej
    PAUSE_SEC     = 0.4       # dluzsza pauza miedzy akapitami
    ENHANCE_NFE   = 128       # max jakosc Resemble Enhance
    ENHANCE_LAMBD = 0.6       # lagodniejsze odszumianie - zachowuje detale glosu
    ENHANCE_TAU   = 0.35      # mniejsza losowosc enhancera
else:
    EXAGGERATION  = 1.05      # 1.0-1.15 - wyrazniejsza intonacja
    CFG_WEIGHT    = 0.45      # nisko - wiecej swobody
    TEMPERATURE   = 0.98      # wysoko - roznorodnosc prozodii
    SLOW_FACTOR   = 0.96      # delikatne przyspieszenie
    PAUSE_SEC     = 0.25      # krotka pauza miedzy akapitami
    ENHANCE_NFE   = 64        # 32=szybki, 64=sredni, 128=max jakosc
    ENHANCE_LAMBD = 0.9       # mocne odszumianie
    ENHANCE_TAU   = 0.5       # zbalansowane

LOUDNESS      = -17       # lekko glosniej niz -18
LRA           = 11        # wysoko -> zachowuje dynamike

# Resemble Enhance
ENABLE_ENHANCE = True     # True = uzyj Resemble Enhance

RAW_FILE               = 'troja_dluzszy_raw.wav'
RAW_ENHANCED_FILE      = 'troja_dluzszy_raw_enhanced.wav'
RAW_ENHANCED_NORM_FILE = 'troja_dluzszy_raw_enhanced_norm.wav'
OUTPUT_FILE            = 'troja_dluzszy_podcast.wav'
ENHANCED_FILE          = 'troja_dluzszy_enhanced.wav'

# Dluzszy tekst - historia Troi + Iliada
paragraphs = [
    'Troja byla miastem polozonym w polnocno-zachodniej Anatolii, w poblizu ciesniny Dardanele. Ta strategiczna lokalizacja uczynila ja przez dlugi czas waznym miejscem na mapie starozytnego swiata.',
    'To tutaj krzyzowaly sie szlaki handlowe, ktore laczyla Europe z Azja. Miasto bylo punktem styku pomiedzy swiatem nadmorskim a ladowym.',
    'Troja nie byla zwykla osada. Bylo to miejsce, w ktorym koncentrowaly sie handel, wladza i konflikty. Z biegiem lat zyskala status jednego z najbardziej znanych miejsc w mitologii starozytnej.',
    'Wedlug tradycji, Troja zostala zalozona przez Ilosa, syna Troosa, od ktorego pochodzi nazwa miasta - Ilion. Miasto rozwijalo sie przez wieki, osiagajac szczyt potegi w epoce brazu.',
    'Najbardziej znana jest jednak dzieki wojnie trojanskiej, opisanej przez Homera w Iliadzie. Wedlug mitu, wszystko zaczelo sie od jablka niezgody i porwania Heleny przez Parysa.',
    'Dziesiec lat trwalo oblezenie Troi przez Grekow. Achilles, Hektor, Odyseusz - to postacie, ktore na zawsze wryly sie w pamiec ludzkosci.',
    'Ostatecznie Troja padla nie przez sile oreza, lecz podstep - drewniany kon, w ktorym ukryli sie wojownicy. Po zdobyciu miasta Grecy spalili je doszczetnie.',
    'Przez wieki uwazano, ze Troja to tylko mit. Dopiero w XIX wieku Heinrich Schliemann rozpoczal wykopaliska w Hisarlik i odkryl warstwy archeologiczne potwierdzajace istnienie poteznego miasta w tym miejscu.',
    'Dzis Troja jest wpisana na liste swiatowego dziedzictwa UNESCO i przypomina nam, jak cienka jest granica miedzy mitem a historia.'
]

# =============================================
# KROK 1: Wymowa - zamien nazwy wlasne na fonetyczne
# =============================================
print('Ladowanie regul wymowy...')
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
print('Ladowanie modelu Chatterbox...')
model = ChatterboxMultilingualTTS.from_pretrained(device='cuda')
print('Model zaladowany.')

# Generuj cisza na pauzy miedzy akapitami
pause_samples = int(PAUSE_SEC * model.sr)
silence = torch.zeros(1, pause_samples)

audio_chunks = []
for i, text in enumerate(processed_paragraphs):
    print(f'Generuje akapit {i+1}/{len(processed_paragraphs)}...')
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
        print("Uwaga: temperature nieobslugiwane w tej wersji - pomijam")

    wav = model.generate(**kwargs)
    audio_chunks.append(wav)

    # Dodaj pauze po kazdym akapicie (oprocz ostatniego)
    if i < len(processed_paragraphs) - 1:
        audio_chunks.append(silence)

# Sklej chunki z pauzami
full_wav = torch.cat(audio_chunks, dim=1)

ta.save(RAW_FILE, full_wav, model.sr)
print(f'Zapisano surowy plik: {RAW_FILE}')

# Zwolnij model Chatterbox z GPU
del model
import gc
gc.collect()
torch.cuda.empty_cache()
print('Model Chatterbox zwolniony z GPU.')

# =============================================
# KROK 3: Resemble Enhance na surowym audio (RAW -> RAW_ENHANCED)
# =============================================
def run_enhance(input_file, output_file, label):
    """Uruchom Resemble Enhance na pliku audio"""
    try:
        from resemble_enhance.enhancer.inference import enhance

        print(f'Resemble Enhance [{label}] (nfe={ENHANCE_NFE}, lambd={ENHANCE_LAMBD}, tau={ENHANCE_TAU})...')
        dwav, sr = ta.load(input_file)
        dwav = dwav.squeeze(0) if dwav.shape[0] == 1 else torch.mean(dwav, dim=0)

        enhanced, new_sr = enhance(
            dwav, sr, 'cuda',
            nfe=ENHANCE_NFE,
            solver='midpoint',
            lambd=ENHANCE_LAMBD,
            tau=ENHANCE_TAU
        )

        if enhanced.dim() == 1:
            enhanced = enhanced.unsqueeze(0)
        ta.save(output_file, enhanced.cpu(), new_sr)
        print(f'Zapisano: {output_file}')
        return True

    except ImportError:
        print('Resemble Enhance niedostepny - pomijam. Uruchom: python scripts/patch_resemble_enhance.py')
        return False
    except Exception as e:
        print(f'Resemble Enhance blad: {e} - pomijam')
        return False

if ENABLE_ENHANCE:
    run_enhance(RAW_FILE, RAW_ENHANCED_FILE, 'surowy')

    # Normalizacja glosnosci na raw_enhanced (-16 LUFS = standard podcastowy)
    if os.path.exists(RAW_ENHANCED_FILE):
        print(f'Normalizacja glosnosci ({LOUDNESS} LUFS)...')
        subprocess.run([
            'ffmpeg', '-y',
            '-i', RAW_ENHANCED_FILE,
            '-af', f'loudnorm=I={LOUDNESS}:TP=-1.5:LRA={LRA}',
            RAW_ENHANCED_NORM_FILE
        ], check=True)
        print(f'Zapisano znormalizowany: {RAW_ENHANCED_NORM_FILE}')

# =============================================
# KROK 4: ffmpeg - minimalna obrobka
# =============================================
print('Przetwarzam ffmpeg - minimalna obrobka...')
subprocess.run([
    'ffmpeg', '-y',
    '-i', RAW_FILE,
    '-af', f'atempo={SLOW_FACTOR},afftdn=nf=-30,volume=2.5dB',
    '-ar', '48000',
    OUTPUT_FILE
], check=True)
print(f'Zapisano po ffmpeg: {OUTPUT_FILE}')

# =============================================
# KROK 5: Resemble Enhance na przetworzonym audio (ffmpeg -> ENHANCED)
# =============================================
if ENABLE_ENHANCE:
    run_enhance(OUTPUT_FILE, ENHANCED_FILE, 'po ffmpeg')

# =============================================
# PODSUMOWANIE
# =============================================
print()
print('=' * 50)
print('Gotowe! Pliki:')
print(f'  1. Surowy TTS:            {os.path.abspath(RAW_FILE)}')
if ENABLE_ENHANCE and os.path.exists(RAW_ENHANCED_FILE):
    print(f'  2. Surowy + Enhance:      {os.path.abspath(RAW_ENHANCED_FILE)}')
if ENABLE_ENHANCE and os.path.exists(RAW_ENHANCED_NORM_FILE):
    print(f'  2b. Enhance + loudnorm:   {os.path.abspath(RAW_ENHANCED_NORM_FILE)}  <-- BEST')
print(f'  3. Po ffmpeg:             {os.path.abspath(OUTPUT_FILE)}')
if ENABLE_ENHANCE and os.path.exists(ENHANCED_FILE):
    print(f'  4. ffmpeg + Enhance:      {os.path.abspath(ENHANCED_FILE)}')
print()
if HQ_MODE:
    print('Tryb: HIGH QUALITY')
    print(f'  exaggeration={EXAGGERATION}, cfg={CFG_WEIGHT}, temp={TEMPERATURE}')
    print(f'  nfe={ENHANCE_NFE}, lambd={ENHANCE_LAMBD}, tau={ENHANCE_TAU}')
else:
    print('Tryb: STANDARD (uzyj --hq dla wyzszej jakosci)')
print('=' * 50)
