# chatterbox_podcast_troja.py
# Uruchom: python chatterbox_podcast_troja.py
#
# Porownanie enhancerow:
#   python chatterbox_podcast_troja.py              - Resemble Enhance
#   python chatterbox_podcast_troja.py --clearvoice  - ClearerVoice-Studio
#   python chatterbox_podcast_troja.py --all         - wszystkie warianty
#   python chatterbox_podcast_troja.py --hq          - tryb HQ (nfe=128)
#
# Generuje pliki do porownania:
#   1. troja_raw.wav                    - surowy TTS
#   2. troja_raw_norm.wav               - surowy TTS + loudnorm
#   3. troja_resemble.wav               - RAW + Resemble Enhance + loudnorm
#   4. troja_clearvoice.wav             - RAW + ClearerVoice + loudnorm
#   5. troja_resemble_clearvoice.wav    - RAW + Resemble + ClearerVoice + loudnorm

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
import torch
import torchaudio as ta
import subprocess
import os
import sys
import pathlib
import platform
import gc

# Fix PosixPath on Windows (for Resemble Enhance model loading)
if platform.system() == "Windows":
    pathlib.PosixPath = pathlib.WindowsPath

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.services.phonetics import PhoneticsService

# =============================================
# FLAGI
# =============================================
HQ_MODE = '--hq' in sys.argv
USE_CLEARVOICE = '--clearvoice' in sys.argv or '--all' in sys.argv
USE_RESEMBLE = '--clearvoice' not in sys.argv or '--all' in sys.argv

# =============================================
# KONFIGURACJA
# =============================================
if HQ_MODE:
    print('=== TRYB HIGH QUALITY ===')
    EXAGGERATION  = 0.7
    CFG_WEIGHT    = 0.55
    TEMPERATURE   = 0.92
    PAUSE_SEC     = 0.4
    ENHANCE_NFE   = 128
    ENHANCE_LAMBD = 0.6
    ENHANCE_TAU   = 0.35
else:
    EXAGGERATION  = 1.05
    CFG_WEIGHT    = 0.45
    TEMPERATURE   = 0.98
    PAUSE_SEC     = 0.25
    ENHANCE_NFE   = 64
    ENHANCE_LAMBD = 0.9
    ENHANCE_TAU   = 0.5

LOUDNESS = -17
LRA      = 11

# Pliki wyjsciowe
RAW_FILE                    = 'troja_raw.wav'
RAW_NORM_FILE               = 'troja_raw_norm.wav'
RESEMBLE_FILE               = 'troja_resemble.wav'
CLEARVOICE_FILE             = 'troja_clearvoice.wav'
RESEMBLE_CLEARVOICE_FILE    = 'troja_resemble_clearvoice.wav'

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
# HELPERS
# =============================================
def loudnorm(input_file, output_file):
    """Normalizacja glosnosci do LUFS"""
    print(f'  loudnorm ({LOUDNESS} LUFS): {os.path.basename(output_file)}')
    subprocess.run([
        'ffmpeg', '-y',
        '-i', input_file,
        '-af', f'loudnorm=I={LOUDNESS}:TP=-1.5:LRA={LRA}',
        output_file
    ], check=True, capture_output=True)


def run_resemble(input_file, output_file):
    """Resemble Enhance"""
    try:
        from resemble_enhance.enhancer.inference import enhance

        print(f'  Resemble Enhance (nfe={ENHANCE_NFE}, lambd={ENHANCE_LAMBD})...')
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
        print(f'  Zapisano: {output_file}')
        return True

    except ImportError:
        print('  Resemble Enhance niedostepny - pip install resemble-enhance')
        return False
    except Exception as e:
        print(f'  Resemble Enhance blad: {e}')
        return False


def run_clearvoice(input_file, output_file):
    """ClearerVoice-Studio MossFormer2 48kHz enhancement"""
    try:
        from clearvoice import ClearVoice

        print(f'  ClearerVoice-Studio (MossFormer2_SE_48K)...')
        cv = ClearVoice(
            task='speech_enhancement',
            model_names=['MossFormer2_SE_48K']
        )

        output_wav = cv(input_path=input_file, online_write=False)
        cv.write(output_wav, output_path=output_file)
        print(f'  Zapisano: {output_file}')
        return True

    except ImportError:
        print('  ClearerVoice niedostepny - pip install clearvoice')
        return False
    except Exception as e:
        print(f'  ClearerVoice blad: {e}')
        return False


def free_gpu():
    """Zwolnij GPU"""
    gc.collect()
    torch.cuda.empty_cache()


# =============================================
# KROK 1: Wymowa
# =============================================
print('=' * 50)
print('KROK 1: Reguly wymowy')
print('=' * 50)
phonetics = PhoneticsService(csv_path='./pronunciations.csv')

processed_paragraphs = []
for i, text in enumerate(paragraphs):
    fixed, count = phonetics.apply_text_replacements(text)
    if count > 0:
        print(f'  Akapit {i+1}: {count} zamian')
    processed_paragraphs.append(fixed)

# =============================================
# KROK 2: Generowanie TTS (Chatterbox)
# =============================================
print('=' * 50)
print('KROK 2: Chatterbox TTS')
print('=' * 50)

# Uzyj istniejacego RAW jesli juz jest (oszczedza czas przy testach enhancera)
if os.path.exists(RAW_FILE) and '--regenerate' not in sys.argv:
    print(f'  Plik {RAW_FILE} juz istnieje - pomijam generowanie TTS')
    print(f'  (uzyj --regenerate zeby wygenerowac od nowa)')
else:
    print('  Ladowanie modelu Chatterbox...')
    model = ChatterboxMultilingualTTS.from_pretrained(device='cuda')
    print(f'  Model zaladowany (sr={model.sr})')

    pause_samples = int(PAUSE_SEC * model.sr)
    silence = torch.zeros(1, pause_samples)

    audio_chunks = []
    for i, text in enumerate(processed_paragraphs):
        print(f'  Generuje akapit {i+1}/{len(processed_paragraphs)}...')
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
            pass

        wav = model.generate(**kwargs)
        audio_chunks.append(wav)
        if i < len(processed_paragraphs) - 1:
            audio_chunks.append(silence)

    full_wav = torch.cat(audio_chunks, dim=1)
    ta.save(RAW_FILE, full_wav, model.sr)
    print(f'  Zapisano: {RAW_FILE}')

    del model
    free_gpu()
    print('  Model Chatterbox zwolniony z GPU')

# =============================================
# KROK 3: Wariant 1 - RAW + loudnorm (baseline)
# =============================================
print('=' * 50)
print('WARIANT 1: RAW + loudnorm')
print('=' * 50)
loudnorm(RAW_FILE, RAW_NORM_FILE)

# =============================================
# KROK 4: Wariant 2 - RAW + Resemble + loudnorm
# =============================================
if USE_RESEMBLE:
    print('=' * 50)
    print('WARIANT 2: RAW + Resemble Enhance + loudnorm')
    print('=' * 50)
    tmp_resemble = '_tmp_resemble.wav'
    if run_resemble(RAW_FILE, tmp_resemble):
        loudnorm(tmp_resemble, RESEMBLE_FILE)
        os.remove(tmp_resemble)
        free_gpu()

# =============================================
# KROK 5: Wariant 3 - RAW + ClearerVoice + loudnorm
# =============================================
if USE_CLEARVOICE:
    print('=' * 50)
    print('WARIANT 3: RAW + ClearerVoice + loudnorm')
    print('=' * 50)
    tmp_cv = '_tmp_clearvoice.wav'
    if run_clearvoice(RAW_FILE, tmp_cv):
        loudnorm(tmp_cv, CLEARVOICE_FILE)
        os.remove(tmp_cv)
        free_gpu()

# =============================================
# KROK 6: Wariant 4 - RAW + Resemble + ClearerVoice + loudnorm
# =============================================
if USE_RESEMBLE and USE_CLEARVOICE:
    print('=' * 50)
    print('WARIANT 4: RAW + Resemble + ClearerVoice + loudnorm')
    print('=' * 50)
    tmp_resemble2 = '_tmp_resemble2.wav'
    tmp_both = '_tmp_both.wav'

    ok = False
    if os.path.exists(RESEMBLE_FILE):
        # Uzyj juz istniejacego resemble (przed loudnorm)
        # Musimy odtworzyc wersje bez loudnorm
        if run_resemble(RAW_FILE, tmp_resemble2):
            if run_clearvoice(tmp_resemble2, tmp_both):
                loudnorm(tmp_both, RESEMBLE_CLEARVOICE_FILE)
                ok = True
    else:
        if run_resemble(RAW_FILE, tmp_resemble2):
            if run_clearvoice(tmp_resemble2, tmp_both):
                loudnorm(tmp_both, RESEMBLE_CLEARVOICE_FILE)
                ok = True

    # Cleanup
    for f in [tmp_resemble2, tmp_both]:
        if os.path.exists(f):
            os.remove(f)
    free_gpu()

# =============================================
# PODSUMOWANIE
# =============================================
print()
print('=' * 60)
print('POROWNANIE - odsluchaj i wybierz najlepszy:')
print('=' * 60)

results = [
    ('1. RAW + loudnorm (baseline)', RAW_NORM_FILE),
    ('2. RAW + Resemble + loudnorm', RESEMBLE_FILE),
    ('3. RAW + ClearerVoice + loudnorm', CLEARVOICE_FILE),
    ('4. RAW + Resemble + ClearerVoice + loudnorm', RESEMBLE_CLEARVOICE_FILE),
]

for label, filepath in results:
    if os.path.exists(filepath):
        size_mb = os.path.getsize(filepath) / 1024 / 1024
        print(f'  {label}')
        print(f'     -> {os.path.abspath(filepath)} ({size_mb:.1f} MB)')
    else:
        print(f'  {label} -- NIE WYGENEROWANO')

print()
print(f'  Surowy TTS (bez enhance): {os.path.abspath(RAW_FILE)}')
print()
if HQ_MODE:
    print(f'  Tryb: HQ (exagg={EXAGGERATION}, nfe={ENHANCE_NFE})')
else:
    print(f'  Tryb: STANDARD')
print('=' * 60)
