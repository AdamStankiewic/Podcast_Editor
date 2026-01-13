#!/usr/bin/env python3
"""
Simple Azure TTS test to verify SDK works in Docker environment
Run this to diagnose Azure Speech SDK issues
"""
import os
import sys
from pathlib import Path

def test_azure_import():
    """Test if Azure SDK can be imported"""
    print("=" * 60)
    print("TEST 1: Importing Azure Speech SDK")
    print("=" * 60)
    try:
        import azure.cognitiveservices.speech as speechsdk
        print("✓ Azure Speech SDK imported successfully")
        print(f"  Version: {speechsdk.__version__ if hasattr(speechsdk, '__version__') else 'unknown'}")
        return True
    except Exception as e:
        print(f"✗ Failed to import Azure Speech SDK: {e}")
        return False

def test_azure_config():
    """Test if Azure credentials are configured"""
    print("\n" + "=" * 60)
    print("TEST 2: Checking Azure credentials")
    print("=" * 60)

    key = os.getenv("SPEECH_KEY")
    region = os.getenv("SPEECH_REGION")

    if not key:
        print("✗ SPEECH_KEY not set in environment")
        return False
    if not region:
        print("✗ SPEECH_REGION not set in environment")
        return False

    print(f"✓ SPEECH_KEY: {'*' * 8}{key[-4:]}")
    print(f"✓ SPEECH_REGION: {region}")
    return True

def test_azure_synthesizer():
    """Test if Azure synthesizer can be initialized"""
    print("\n" + "=" * 60)
    print("TEST 3: Initializing Azure Speech Synthesizer")
    print("=" * 60)

    try:
        import azure.cognitiveservices.speech as speechsdk

        key = os.getenv("SPEECH_KEY")
        region = os.getenv("SPEECH_REGION")

        speech_config = speechsdk.SpeechConfig(
            subscription=key,
            region=region
        )
        speech_config.speech_synthesis_voice_name = "en-GB-OllieMultilingualNeural"

        # Use null audio output (synthesize to memory, don't save)
        print("Creating synthesizer...")
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None  # None = synthesize to result object
        )

        print("✓ Synthesizer created successfully")
        return True

    except Exception as e:
        print(f"✗ Failed to create synthesizer: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_simple_synthesis():
    """Test actual TTS synthesis"""
    print("\n" + "=" * 60)
    print("TEST 4: Testing simple TTS synthesis")
    print("=" * 60)

    try:
        import azure.cognitiveservices.speech as speechsdk

        key = os.getenv("SPEECH_KEY")
        region = os.getenv("SPEECH_REGION")

        speech_config = speechsdk.SpeechConfig(
            subscription=key,
            region=region
        )
        speech_config.speech_synthesis_voice_name = "en-GB-OllieMultilingualNeural"
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )

        # Create temp output
        output_file = "/tmp/test_azure_tts.wav"
        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_file)

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_config
        )

        test_text = "To jest test Azure TTS w języku polskim."
        print(f"Synthesizing: '{test_text}'")

        result = synthesizer.speak_text_async(test_text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"✓ Synthesis successful!")
            if Path(output_file).exists():
                size = Path(output_file).stat().st_size
                print(f"  Output file: {output_file} ({size} bytes)")
                Path(output_file).unlink()  # Clean up
            return True
        else:
            print(f"✗ Synthesis failed: {result.reason}")
            if result.cancellation_details:
                print(f"  Details: {result.cancellation_details}")
            return False

    except Exception as e:
        print(f"✗ Synthesis test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n🔍 Azure TTS Diagnostic Test Suite")
    print("=" * 60)

    results = []

    # Test 1: Import
    results.append(("Import Azure SDK", test_azure_import()))

    if not results[-1][1]:
        print("\n❌ Cannot proceed - Azure SDK import failed")
        print("This indicates missing system libraries.")
        print("Make sure Docker image was rebuilt with: docker compose build --no-cache")
        sys.exit(1)

    # Test 2: Config
    results.append(("Check credentials", test_azure_config()))

    if not results[-1][1]:
        print("\n❌ Cannot proceed - Azure credentials not configured")
        print("Make sure .env file has SPEECH_KEY and SPEECH_REGION")
        sys.exit(1)

    # Test 3: Synthesizer init
    results.append(("Initialize synthesizer", test_azure_synthesizer()))

    if not results[-1][1]:
        print("\n❌ Synthesizer initialization failed")
        print("This is the main error - likely missing system libraries")
        sys.exit(1)

    # Test 4: Actual synthesis
    results.append(("Simple synthesis", test_simple_synthesis()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(r[1] for r in results)

    if all_passed:
        print("\n✅ ALL TESTS PASSED - Azure TTS is working!")
        print("You can now run the full pipeline.")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED - See errors above")
        sys.exit(1)

if __name__ == "__main__":
    main()
