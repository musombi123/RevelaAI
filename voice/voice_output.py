import os
import pyttsx3
import tempfile

IS_PRODUCTION = os.getenv("RENDER") == "true" or os.getenv("ENV") == "production"

def speak(text: str):
    """
    Speak text locally.
    In production, this becomes a no-op to avoid crashes.
    """
    if IS_PRODUCTION:
        # Do nothing in cloud environments
        return

    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    engine.setProperty("volume", 1.0)
    engine.say(text)
    engine.runAndWait()


def text_to_speech_file(text: str, filename: str = None) -> str:
    """
    Converts text to speech and returns a WAV file path.
    SAFE for Render / cloud.
    """
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    engine.setProperty("volume", 1.0)

    if filename is None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        filename = tmp.name
        tmp.close()

    engine.save_to_file(text, filename)
    engine.runAndWait()

    return filename
