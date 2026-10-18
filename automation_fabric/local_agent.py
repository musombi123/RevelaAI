"""Loopback-only companion agent for executing approved tasks on the installed device.

Run with: python -m automation_fabric.local_agent
The server binds to 127.0.0.1 only. Never change this to 0.0.0.0.
"""
from __future__ import annotations

import argparse
import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, make_response, request

_CONFIG_DIR = Path.home() / ".revelaai"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
os.environ.setdefault("REVELAAI_AUTOMATION_DB", str(_CONFIG_DIR / "automation-fabric.sqlite3"))
os.environ.setdefault("REVELAAI_AUTOMATION_WORKSPACE", str(Path.home() / "RevelaAIWorkspace"))

from automation_fabric.http import create_automation_blueprint
from automation_fabric.store import default_db_path


TOKEN_PATH = _CONFIG_DIR / "automation-fabric.token"


def _load_or_create_token() -> tuple[str, bool]:
    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(token) >= 40:
            return token, False
    token = secrets.token_urlsafe(48)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass
    return token, True


def _allowed_origins() -> set[str]:
    return {
        item.strip().rstrip("/")
        for item in os.getenv("REVELAAI_AUTOMATION_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }


def create_local_app(token: str | None = None) -> Flask:
    expected_token = token or _load_or_create_token()[0]
    app = Flask("revelaai_automation_local_agent")
    workspace_root = Path(os.environ["REVELAAI_AUTOMATION_WORKSPACE"]).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def authenticate_local():
        # Flask's remote_addr reflects the connected peer, not X-Forwarded-For.
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return None, (jsonify(status="error", code="loopback_only"), 403)
        authorization = request.headers.get("Authorization", "")
        provided = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if not provided or not hmac.compare_digest(provided, expected_token):
            return None, (jsonify(status="error", code="local_token_required"), 401)
        return "local-device", None

    def workspace_for_local_user(_principal: str) -> Path:
        return workspace_root

    app.register_blueprint(create_automation_blueprint(
        "automation_fabric_local_bp",
        auth_resolver=authenticate_local,
        workspace_resolver=workspace_for_local_user,
        database_resolver=default_db_path,
        local_mode=True,
    ), url_prefix="/api/v1")

    @app.before_request
    def enforce_origin_and_auth_boundary():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify(status="error", code="loopback_only"), 403
        origin = (request.headers.get("Origin") or "").rstrip("/")
        allowed = _allowed_origins()
        if origin and origin not in allowed:
            return jsonify(status="error", code="origin_not_allowed",
                           message="Add this exact frontend origin to REVELAAI_AUTOMATION_ALLOWED_ORIGINS to enable browser access."), 403
        if request.method == "OPTIONS":
            if not origin or origin not in allowed:
                return jsonify(status="error", code="origin_not_allowed"), 403
            response = make_response("", 204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Max-Age"] = "300"
            return response
        return None

    @app.after_request
    def add_explicit_cors_headers(response):
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin and origin in _allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the loopback-only RevelaAI Automation Fabric agent.")
    parser.add_argument("--host", default="127.0.0.1", help="Only 127.0.0.1 is permitted.")
    parser.add_argument("--port", type=int, default=38741)
    parser.add_argument("--show-token", action="store_true", help="Print the local bearer token for deliberate manual setup.")
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("For safety, Automation Fabric only binds to 127.0.0.1.")
    token, created = _load_or_create_token()
    print("RevelaAI Automation Fabric local agent")
    print("Endpoint: http://127.0.0.1:{}/api/v1".format(args.port))
    print("Workspace: {}".format(os.environ["REVELAAI_AUTOMATION_WORKSPACE"]))
    print("Token file: {}".format(TOKEN_PATH))
    if created or args.show_token:
        print("Local bearer token (keep private): {}".format(token))
    else:
        print("Token is stored securely; use --show-token only when you need to copy it.")
    print("Safety: loopback-only, no shell execution, no generated-code auto-run.")
    create_local_app(token).run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
