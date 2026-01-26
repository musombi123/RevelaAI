from datetime import datetime
from config.db import memory_col, messages_col

def save_memory(user_id, key: str, value: str, mem_type: str):
    item = {
        "userId": user_id,
        "key": key,
        "value": value,
        "type": mem_type,
        "createdAt": datetime.utcnow()
    }
    result = memory_col.insert_one(item)
    item["_id"] = result.inserted_id
    return item

def get_memory(user_id):
    return list(memory_col.find({"userId": user_id}).sort("createdAt", -1))

def get_history(user_id, limit: int = 50):
    return list(messages_col.find({"userId": user_id}).sort("createdAt", -1).limit(limit))
