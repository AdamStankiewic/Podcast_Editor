"""
Test różnych głosów Azure TTS dla FR i EN
Porównanie: Ollie vs Henri dla francuskiego, Ollie dla angielskiego
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import azure.cognitiveservices.speech as speechsdk

load_dotenv()

# Azure credentials
SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

if not SPEECH_KEY or not SPEECH_REGION:
    print("❌ ERROR: Azure Speech credentials not found!")
    print("\nPlease create a .env file with your Azure credentials:")
    print("  SPEECH_KEY=your_azure_speech_key")
    print("  SPEECH_REGION=northeurope")
    print("\nOr export them as environment variables:")
    print("  export SPEECH_KEY='your_key'")
    print("  export SPEECH_REGION='northeurope'")
    exit(1)

# Test text (krótki fragment o Jedwabnym Szlaku)
TEST_TEXT_FR = """
Bien avant que la Route de la Soie ne soit établie comme réseau commercial historique,
il existait déjà à l'âge du bronze, c'est-à-dire à partir d'environ deux mille ans avant notre ère,
les premières liaisons commerciales interrégionales qui peuvent être considérées comme les précurseurs
de la Route de la Soie ultérieure.
"""

TEST_TEXT_EN = """
Long before the Silk Road was established as a historic trade network,
there already existed in the Bronze Age, that is from around two thousand years before our era,
the first interregional trade connections that can be considered as precursors
of the later Silk Road.
"""

# Konfiguracja głosów do testowania
VOICES_TO_TEST = {
    # FRANCUSKI
    "FR_Ollie_Multilingual": {
        "voice": "en-GB-OllieMultilingualNeural",
        "language": "fr-FR",
        "text": TEST_TEXT_FR,
        "description": "🇫🇷 Ollie Multilingual (British voice speaking French)"
    },
    "FR_Henri_Neural": {
        "voice": "fr-FR-HenriNeural",
        "language": "fr-FR",
        "text": TEST_TEXT_FR,
        "description": "🇫🇷 Henri (Native French voice)"
    },
    "FR_Alain_Neural": {
        "voice": "fr-FR-AlainNeural",
        "language": "fr-FR",
        "text": TEST_TEXT_FR,
        "description": "🇫🇷 Alain (Native French voice - alternative)"
    },

    # ANGIELSKI
    "EN_Ollie_Neural": {
        "voice": "en-GB-OllieMultilingualNeural",
        "language": "en-GB",
        "text": TEST_TEXT_EN,
        "description": "🇬🇧 Ollie Multilingual (British English)"
    },
    "EN_Ryan_Neural": {
        "voice": "en-GB-RyanNeural",
        "language": "en-GB",
        "text": TEST_TEXT_EN,
        "description": "🇬🇧 Ryan (British English - alternative)"
    },
}

def create_ssml(voice: str, language: str, text: str, use_hd: bool = True) -> str:
    """Tworzy SSML dla danego głosu"""

    # Dla Multilingual NIE używaj HD (już jest wysokiej jakości)
    # Dla innych głosów spróbuj HD tylko jeśli use_hd=True
    if use_hd and "Multilingual" not in voice:
        # Próba z DragonHDLatestNeural (może nie działać dla wszystkich głosów)
        voice_hd = f"{voice.replace('Neural', '')}:DragonHDLatestNeural"
    else:
        voice_hd = voice

    ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">
  <voice name="{voice_hd}">
    <prosody rate="-8%" pitch="0%">
      <lang xml:lang="{language}">
        {text.strip()}
      </lang>
    </prosody>
  </voice>
</speak>"""

    return ssml, voice_hd

def synthesize_voice(voice_name: str, config: dict, output_dir: Path):
    """Generuje audio dla danego głosu"""

    print(f"\n{'='*60}")
    print(f"Testing: {voice_name}")
    print(f"Description: {config['description']}")
    print(f"Voice: {config['voice']}")
    print(f"Language: {config['language']}")

    # Konfiguracja Azure Speech
    speech_config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SPEECH_REGION
    )

    # Output file
    output_file = output_dir / f"{voice_name}.wav"
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_file))

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    # Spróbuj z HD, jeśli się nie uda - fallback na normalny
    try_hd = True
    success = False

    for attempt in range(2):
        ssml, voice_used = create_ssml(
            config['voice'],
            config['language'],
            config['text'],
            use_hd=try_hd
        )

        print(f"Attempt {attempt + 1}: Using voice '{voice_used}'")

        result = synthesizer.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"✓ Success! Saved to: {output_file.name}")
            print(f"  Voice used: {voice_used}")
            success = True
            break
        elif result.reason == speechsdk.ResultReason.Canceled:
            details = result.cancellation_details
            print(f"✗ Failed: {details.reason}")
            if details.error_details:
                print(f"  Error: {details.error_details}")

            # Jeśli HD nie działa, spróbuj bez HD
            error_msg = str(details.error_details).lower()
            if try_hd and ("not found" in error_msg or "unsupported" in error_msg):
                print(f"  DragonHD not available, trying standard Neural...")
                try_hd = False
            else:
                break

    if not success:
        print(f"✗ Failed to synthesize {voice_name}")

    # Cleanup
    del synthesizer
    del audio_config

def main():
    print("🎙️  Azure TTS Voice Comparison Test")
    print("="*60)
    print("Testing voices for French and English")
    print("Output directory: ./test_voices/")

    # Create output directory
    output_dir = Path("test_voices")
    output_dir.mkdir(exist_ok=True)

    # Test each voice
    for voice_name, config in VOICES_TO_TEST.items():
        try:
            synthesize_voice(voice_name, config, output_dir)
        except Exception as e:
            print(f"✗ Error testing {voice_name}: {e}")

    print("\n" + "="*60)
    print("✓ Testing complete!")
    print(f"Audio files saved in: {output_dir.absolute()}")
    print("\nListen to the files and compare:")
    print("  - FR_Ollie_Multilingual.wav (Ollie speaking French)")
    print("  - FR_Henri_Neural.wav (Native French - Henri)")
    print("  - FR_Alain_Neural.wav (Native French - Alain)")
    print("  - EN_Ollie_Neural.wav (Ollie speaking English)")
    print("  - EN_Ryan_Neural.wav (British English - Ryan)")

if __name__ == "__main__":
    main()
