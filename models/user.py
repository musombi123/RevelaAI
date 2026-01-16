# models/user.py
from dataclasses import dataclass
from typing import List

@dataclass
class User:
    user_id: str
    name: str
    roles: List[str]
