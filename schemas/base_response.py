def base_response(success: bool, query: str, mode: str, data, sources=None, meta=None):
    return {
        "success": success,
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
