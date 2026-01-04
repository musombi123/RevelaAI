import json
import re

def extract_json(text: str):
    """
    Attempts to extract JSON from a text response.
    Returns dict if successful, otherwise None.
    """
    if not text:
        return None

    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to extract JSON block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None

    json_str = match.group(0)

    try:
        return json.loads(json_str)
    except Exception:
        return None


def enforce_base_schema(
    query: str,
    mode: str,
    data,
    sources=None,
    meta=None
):
    """
    Wraps response in RevelaAI base schema.
    """
    return {
        "success": True,
        "query": query,
        "mode": mode,
        "data": data,
        "sources": sources or [],
        "meta": meta or {}
    }


def error_response(code: str, message: str):
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message
        }
    }
