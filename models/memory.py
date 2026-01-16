# models/memory.py
from dataclasses import dataclass

@dataclass
class MemoryItem:
    id: str
    content: str
    user_id: str
