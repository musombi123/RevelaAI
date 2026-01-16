# services/memory_service.py
MEMORY_STORE = {}

def remember_item(user_id: str, content: str):
    item_id = str(len(MEMORY_STORE) + 1)
    MEMORY_STORE[item_id] = {"user_id": user_id, "content": content}
    return item_id

def forget_item(item_id: str):
    if item_id in MEMORY_STORE:
        del MEMORY_STORE[item_id]
        return True
    return False
