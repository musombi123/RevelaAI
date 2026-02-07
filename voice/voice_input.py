import os
import json
import queue
import time
from vosk import Model, KaldiRecognizer

# -------------------------------
# Detect cloud environment
# -------------------------------
IS_RENDER = os.environ.get("RENDER") == "true"

# -------------------------------
# Load Vosk model
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

def callback(indata, frames, time_info, status):
    """
    Sounddevice callback: push audio bytes into queue
    """
    q.put(bytes(indata))

def listen(timeout=10):
    """
    Listen to microphone and return recognized text.
    - Uses partial results for real-time transcription
    - Stops automatically after 'timeout' seconds
    - Returns empty string on cloud environments
    """
    if IS_RENDER:
        print("⚠️ Microphone disabled on Render environment")
        return ""

    try:
        import sounddevice as sd
    except ImportError as e:
        print("❌ sounddevice unavailable:", e)
        return ""

    recognizer = KaldiRecognizer(VOSK_MODEL, 16000)
    text_output = []

    start_time = time.time()

    try:
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=8000,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            print("🎤 Listening... Speak now!")
            while time.time() - start_time < timeout:
                if not q.empty():
                    data = q.get()
                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        if res.get("text"):
                            print("✅ Recognized:", res["text"])
                            text_output.append(res["text"])
                    else:
                        # Show partial transcription
                        partial = json.loads(recognizer.PartialResult())
                        if partial.get("partial"):
                            print("⏳ Partial:", partial["partial"])
    except Exception as e:
        print("❌ Audio input error:", e)
        return ""

    return " ".join(text_output).strip()
