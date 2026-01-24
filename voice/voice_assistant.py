from services.brain import generate_response
from utils.utils import preprocess, postprocess

def run_voice_assistant(user_text: str):
    """
    Backend voice processor.
    Receives text from frontend (microphone handled client-side),
    generates AI response, and returns text for TTS playback.
    """
    try:
        if not user_text or not user_text.strip():
            return "", "I didn't catch that. Please speak again."

        # Step 1: Preprocess
        clean_text = preprocess(user_text)

        # Step 2: Generate AI response
        ai_response = generate_response(clean_text)

        # Step 3: Postprocess
        final_response = postprocess(ai_response)

        return clean_text, final_response

    except Exception as e:
        return "", f"Voice assistant error: {str(e)}"
