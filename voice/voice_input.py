import os
import json
import queue
from vosk import Model, KaldiRecognizer

# -------------------------------
# Detect cloud environment
# -------------------------------
IS_RENDER = os.environ.get("RENDER") == "true"

# -------------------------------
# Load Vosk model (safe on Render)
# -------------------------------
MODEL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "vosk-model-small-en-us-0.15")
)

print("Using Vosk model path:", MODEL_PATH)
VOSK_MODEL = Model(MODEL_PATH)

# -------------------------------
# Queue for streaming audio
# -------------------------------
q = queue.Queue()

def callback(indata, frames, time, status):
    q.put(bytes(indata))


def listen():
    """
    Listen to microphone and return recognized text.
    SAFE: Will not crash Render.com
    """

    # 🚫 Disable mic on Render
    if IS_RENDER:
        print("⚠️ Microphone disabled on Render environment")
        return ""

    # ✅ Lazy import (LOCAL ONLY)
    try:
        import sounddevice as sd
    except Exception as e:
        print("❌ sounddevice unavailable:", e)
        return ""

    recognizer = KaldiRecognizer(VOSK_MODEL, 16000)

    try:
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            print("🎤 Listening...")
            while True:
                data = q.get()
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "")
                    if text:
                        return text
    except Exception as e:
        print("❌ Audio input error:", e)
        return ""
