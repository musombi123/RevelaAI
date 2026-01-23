import os
import sounddevice as sd
from vosk import Model, KaldiRecognizer
import json
import queue

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

def callback(indata, frames, time, status):
    """Put microphone data into queue"""
    q.put(bytes(indata))

def listen():
    """Listen to microphone and return recognized text"""
    recognizer = KaldiRecognizer(VOSK_MODEL, 16000)

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
