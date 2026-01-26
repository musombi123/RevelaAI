from bson import ObjectId

def serialize_id(doc: dict):
    doc["_id"] = str(doc["_id"])
    return doc

def ensure_object_id(id_str: str):
    try:
        return ObjectId(id_str)
    except Exception:
        return None
