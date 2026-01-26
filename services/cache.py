import os
import time
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("DB_NAME", "revelaai")]
cache_col = db["rss_cache"]

MEMORY_CACHE = {}
CACHE_TTL = 60 * 60  # 1 hour

def cache_results(query: str, data: dict):
    """Save results to MongoDB & memory fallback."""
    try:
        doc = {
            "query": query,
            "data": data,
            "timestamp": int(time.time())
        }
        cache_col.update_one(
            {"query": query},
            {"$set": doc},
            upsert=True
        )
    except Exception:
        MEMORY_CACHE[query] = {"data": data, "timestamp": int(time.time())}

def get_cached_results(query: str) -> dict | None:
    """Retrieve cached search results if still valid."""
    now = int(time.time())
    try:
        doc = cache_col.find_one({"query": query})
        if doc and now - doc["timestamp"] <= CACHE_TTL:
            return doc["data"]
    except Exception:
        pass

    mem = MEMORY_CACHE.get(query)
    if mem and now - mem["timestamp"] <= CACHE_TTL:
        return mem["data"]

    return None
