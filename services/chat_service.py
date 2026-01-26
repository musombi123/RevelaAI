from datetime import datetime
from config.db import messages_col
from services.emotion_service import detect_emotion

def save_message(user_id, role: str, content: str):
    messages_col.insert_one({
        "userId": user_id,
        "role": role,
        "content": content,
        "createdAt": datetime.utcnow()
    })

def generate_reply(user_id, message: str):
    emotion = detect_emotion(message)

    # Save user message
    save_message(user_id, "user", message)

    # Placeholder AI response
    reply = f'🤖 RevelaAI says: I got you. You said: "{message}"'

    # Save AI reply
    save_message(user_id, "ai", reply)

    return {
        "reply": reply,
        "emotion": emotion
    }
