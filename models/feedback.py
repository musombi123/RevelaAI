# models/feedback.py
from dataclasses import dataclass

@dataclass
class Feedback:
    message_id: str
    rating: str
    user_id: str
