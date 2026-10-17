"""Sci-Core uses only the dedicated revelai database and named collections."""
DEFENSIVE_ONLY = True
import os
from pymongo import MongoClient
_client = None
_db = None
def database():
    global _client, _db
    if _db is not None: return _db
    uri = os.getenv("MONGO_URI","").strip()
    if not uri: return None
    _client = MongoClient(uri, serverSelectionTimeoutMS=2500, connectTimeoutMS=2500)
    _db = _client["revelai"]
    return _db
def collection(name):
    if name not in {"research","threats","shields","disasters","hardware_lab"}: raise ValueError("Unknown Sci-Core collection")
    db = database()
    if db is None: raise RuntimeError("MONGO_URI is not configured")
    return db[name]
