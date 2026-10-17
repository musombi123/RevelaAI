"""Legacy-compatible handles for RevelaAI's own database.

RevelaCode owns authentication and users in the separate `revelacode` database.
This module must never expose or create a RevelaAI-side users collection.
All long-term AI data lives in `revelai` on the same MongoDB Atlas cluster.
"""
import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "").strip()
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is required for RevelaAI database access.")

client = MongoClient(MONGO_URI)
db = client["revelai"]

conversations_col = db["conversations"]
memories_col = db["memories"]
ideas_col = db["ideas"]
learnings_col = db["learnings"]

# Backward-compatible names for any legacy AI feature importing these handles.
# They intentionally point to the canonical RevelaAI collections, not users.
memory_col = memories_col
messages_col = conversations_col
