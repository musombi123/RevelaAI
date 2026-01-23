import pyttsx3
import tempfile

def speak(text: str):
    """Speak text immediately (blocking)"""
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1.0)
    engine.say(text)
    engine.runAndWait()

def text_to_speech_file(text: str, filename: str = None) -> str:
    """
    Converts text to speech and returns the path to a WAV file.
    If filename is None, creates a temporary WAV file.
    """
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    engine.setProperty('volume', 1.0)

    if filename is None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        filename = tmp.name
        tmp.close()

    engine.save_to_file(text, filename)
    engine.runAndWait()
    return filename
