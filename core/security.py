# core/security.py

FOUNDER_ROLE = "FOUNDER"
ADMIN_ROLE = "ADMIN"
USER_ROLE = "USER"

def verify_role(required_role: str, user_roles: list):
    if required_role not in user_roles:
        raise PermissionError(f"Access denied. Required role: {required_role}")
