import os
import json
import wave
from vosk import Model, KaldiRecognizer


# ---------------------------------------
# CONFIG
# ---------------------------------------
# Put your Vosk model folder here:
# Example: voice/models/vosk-model-small-en-us-0.15
VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "voice/models/vosk-model-small-en-us-0.15")


def transcribe_audio_file(audio_path: str) -> str:
    """
    Transcribe a WAV audio file to text using Vosk (offline speech recognition).

    Requirements:
    - Audio MUST be WAV format
    - Recommended: mono channel, 16kHz sample rate

    Returns:
    - Transcribed text (string)
    """

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if not os.path.exists(VOSK_MODEL_PATH):
        raise FileNotFoundError(
            f"Vosk model not found at: {VOSK_MODEL_PATH}\n"
            f"Download a Vosk model and place it there."
        )

    # Load model
    model = Model(VOSK_MODEL_PATH)

    # Open audio file
    wf = wave.open(audio_path, "rb")

    # Validate WAV format
    if wf.getnchannels() != 1:
        raise ValueError("Audio must be mono (1 channel). Convert it before transcription.")

    if wf.getsampwidth() != 2:
        raise ValueError("Audio must be 16-bit WAV (sample width = 2).")

    if wf.getcomptype() != "NONE":
        raise ValueError("Audio must be uncompressed PCM WAV.")

    recognizer = KaldiRecognizer(model, wf.getframerate())
    recognizer.SetWords(True)

    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break

        if recognizer.AcceptWaveform(data):
            res = json.loads(recognizer.Result())
            text = res.get("text", "").strip()
            if text:
                results.append(text)

    final_res = json.loads(recognizer.FinalResult())
    final_text = final_res.get("text", "").strip()
    if final_text:
        results.append(final_text)

    wf.close()

    # Join all chunks
    return " ".join(results).strip()
