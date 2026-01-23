from voice.voice_input import listen
from voice.voice_output import speak
from services.brain import generate_response
from utils.utils import preprocess, postprocess

def run_voice_assistant():
    """
    Listen to the user, generate AI response, and speak it.
    Returns the text heard and AI response.
    """
    try:
        # Step 1: Listen to user
        raw_text = listen()
        if not raw_text:
            return "", "I didn't catch that. Please speak again."

        # Step 2: Preprocess text
        user_text = preprocess(raw_text)

        # Step 3: Generate AI response
        ai_response = generate_response(user_text)

        # Step 4: Postprocess output
        final_response = postprocess(ai_response)

        # Step 5: Speak the response
        speak(final_response)

        return raw_text, final_response

    except Exception as e:
        # Catch errors to prevent Flask from crashing
        return "", f"Voice assistant error: {str(e)}"
