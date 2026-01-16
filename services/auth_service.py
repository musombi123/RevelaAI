# services/auth_service.py

def authenticate(token: str):
    """
    Dummy authentication for Phase One
    """
    # Return mock user
    return {"user_id": "user123", "roles": ["USER"]}
