# chatterbox_test_turbo_en.py
# Test Chatterbox-Turbo (English) vs Chatterbox-Multilingual (English)
#
# Uruchom: python chatterbox_test_turbo_en.py

import torch
import torchaudio as ta
import subprocess
import os
import sys
import pathlib
import platform
import gc

# Fix PosixPath on Windows
if platform.system() == "Windows":
    pathlib.PosixPath = pathlib.WindowsPath

# =============================================
# KONFIGURACJA
# =============================================
PAUSE_SEC = 0.25
LOUDNESS = -17
LRA = 11

# Same Troy story in English
paragraphs = [
    'Troy was a city located in northwestern Anatolia, near the Dardanelles strait. This strategic location made it an important place on the map of the ancient world for a very long time.',
    'It was here that trade routes crossed, connecting Europe with Asia. The city was a meeting point between the maritime and continental worlds.',
    'Troy was no ordinary settlement. It was a place where trade, power, and conflicts converged. Over the years, it gained the status of one of the most famous places in ancient mythology.',
    'According to tradition, Troy was founded by Ilus, son of Tros, from whom the city got its name, Ilion. The city developed over centuries, reaching the peak of its power in the Bronze Age.',
    'However, it is best known for the Trojan War, described by Homer in the Iliad. According to myth, it all began with the apple of discord and the abduction of Helen by Paris.',
    'The siege of Troy by the Greeks lasted ten years. Achilles, Hector, Odysseus [chuckle] these are figures that have been etched into the memory of humanity forever.',
    'Ultimately, Troy fell not by the force of arms, but by cunning. A wooden horse, in which warriors hid themselves. After capturing the city, the Greeks burned it to the ground.',
    'For centuries, Troy was considered merely a myth. It was not until the nineteenth century that Heinrich Schliemann began excavations at Hisarlik and discovered archaeological layers confirming the existence of a powerful city at that location.',
    'Today, Troy is inscribed on the UNESCO World Heritage List and reminds us how thin the line is between myth and history.'
]

# Pliki wyjsciowe
TURBO_RAW = 'troy_turbo_raw.wav'
TURBO_NORM = 'troy_turbo_norm.wav'
MTL_RAW = 'troy_multilingual_raw.wav'
MTL_NORM = 'troy_multilingual_norm.wav'

# =============================================
# HELPERS
# =============================================
def loudnorm(input_file, output_file):
    print(f'  loudnorm ({LOUDNESS} LUFS): {os.path.basename(output_file)}')
    subprocess.run([
        'ffmpeg', '-y',
        '-i', input_file,
        '-af', f'loudnorm=I={LOUDNESS}:TP=-1.5:LRA={LRA}',
        output_file
    ], check=True, capture_output=True)

def free_gpu():
    gc.collect()
    torch.cuda.empty_cache()

# =============================================
# KROK 1: Chatterbox-Turbo (English)
# =============================================
print('=' * 50)
print('KROK 1: Chatterbox-TURBO (English)')
print('=' * 50)

if os.path.exists(TURBO_RAW) and '--regenerate' not in sys.argv:
    print(f'  {TURBO_RAW} juz istnieje - pomijam')
else:
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    print('  Ladowanie modelu Turbo...')
    model = ChatterboxTurboTTS.from_pretrained(device='cuda')
    print(f'  Model zaladowany (sr={model.sr})')

    pause_samples = int(PAUSE_SEC * model.sr)
    silence = torch.zeros(1, pause_samples)

    audio_chunks = []
    for i, text in enumerate(paragraphs):
        print(f'  Generuje akapit {i+1}/{len(paragraphs)}...')
        wav = model.generate(
            text,
            audio_prompt_path='assets/voice_reference.wav'
        )
        audio_chunks.append(wav)
        if i < len(paragraphs) - 1:
            audio_chunks.append(silence)

    full_wav = torch.cat(audio_chunks, dim=1)
    ta.save(TURBO_RAW, full_wav, model.sr)
    print(f'  Zapisano: {TURBO_RAW}')

    del model
    free_gpu()
    print('  Model Turbo zwolniony z GPU')

# =============================================
# KROK 2: Chatterbox-Multilingual (English)
# =============================================
print('=' * 50)
print('KROK 2: Chatterbox-MULTILINGUAL (English)')
print('=' * 50)

if os.path.exists(MTL_RAW) and '--regenerate' not in sys.argv:
    print(f'  {MTL_RAW} juz istnieje - pomijam')
else:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    print('  Ladowanie modelu Multilingual...')
    model = ChatterboxMultilingualTTS.from_pretrained(device='cuda')
    print(f'  Model zaladowany (sr={model.sr})')

    pause_samples = int(PAUSE_SEC * model.sr)
    silence = torch.zeros(1, pause_samples)

    audio_chunks = []
    for i, text in enumerate(paragraphs):
        print(f'  Generuje akapit {i+1}/{len(paragraphs)}...')
        wav = model.generate(
            text,
            audio_prompt_path='assets/voice_reference.wav',
            language_id='en',
            exaggeration=1.05,
            cfg_weight=0.45,
        )
        audio_chunks.append(wav)
        if i < len(paragraphs) - 1:
            audio_chunks.append(silence)

    full_wav = torch.cat(audio_chunks, dim=1)
    ta.save(MTL_RAW, full_wav, model.sr)
    print(f'  Zapisano: {MTL_RAW}')

    del model
    free_gpu()
    print('  Model Multilingual zwolniony z GPU')

# =============================================
# KROK 3: Loudnorm obu
# =============================================
print('=' * 50)
print('KROK 3: Loudnorm')
print('=' * 50)
loudnorm(TURBO_RAW, TURBO_NORM)
loudnorm(MTL_RAW, MTL_NORM)

# =============================================
# PODSUMOWANIE
# =============================================
print()
print('=' * 60)
print('POROWNANIE - Turbo vs Multilingual (English):')
print('=' * 60)

results = [
    ('1. TURBO (English-only, 350M, 6x faster)', TURBO_NORM),
    ('2. MULTILINGUAL (23 lang, 500M)', MTL_NORM),
]

for label, filepath in results:
    if os.path.exists(filepath):
        size_mb = os.path.getsize(filepath) / 1024 / 1024
        print(f'  {label}')
        print(f'     -> {os.path.abspath(filepath)} ({size_mb:.1f} MB)')
    else:
        print(f'  {label} -- NIE WYGENEROWANO')

print()
print('  RAW (bez loudnorm):')
print(f'     Turbo:        {os.path.abspath(TURBO_RAW)}')
print(f'     Multilingual: {os.path.abspath(MTL_RAW)}')
print('=' * 60)
