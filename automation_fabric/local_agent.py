"""Loopback-only FastAPI companion agent for approved local Automation Fabric tasks.

Run with: python -m automation_fabric.local_agent
The socket binds to 127.0.0.1 only, proxy headers are disabled, and browser
origins must be explicitly allowlisted.
"""
from __future__ import annotations

import argparse
import hmac
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

from automation_fabric.http import create_automation_router
from automation_fabric.store import default_db_path

_CONFIG_DIR = Path.home() / ".revelaai"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
os.environ.setdefault("REVELAAI_AUTOMATION_DB", str(_CONFIG_DIR / "automation-fabric.sqlite3"))
os.environ.setdefault("REVELAAI_AUTOMATION_WORKSPACE", str(Path.home() / "RevelaAIWorkspace"))

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


def _is_loopback(request: Request) -> bool:
    # Uvicorn runs with proxy_headers=False so this is the connected peer address,
    # not user-controlled X-Forwarded-For / X-Real-IP metadata.
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1"}


def create_local_app(token: str | None = None) -> FastAPI:
    expected_token = token or _load_or_create_token()[0]
    app = FastAPI(
        title="RevelaAI Automation Fabric Local Agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    workspace_root = Path(
        os.environ["REVELAAI_AUTOMATION_WORKSPACE"]
    ).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        workspace_root.chmod(0o700)
    except OSError:
        pass

    def authenticate_local(request: Request):
        authorization = request.headers.get("Authorization", "")
        provided = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if not provided or not hmac.compare_digest(provided, expected_token):
            return None, JSONResponse(
                {"status": "error", "code": "local_token_required"},
                status_code=401,
            )
        return "local-device", None

    def workspace_for_local_user(_principal: str) -> Path:
        return workspace_root

    app.include_router(
        create_automation_router(
            "automation_fabric_local",
            auth_resolver=authenticate_local,
            workspace_resolver=workspace_for_local_user,
            database_resolver=default_db_path,
            local_mode=True,
            prefix="/api/v1",
        )
    )

    @app.middleware("http")
    async def enforce_origin_and_local_peer(request: Request, call_next):
        if not _is_loopback(request):
            return JSONResponse(
                {"status": "error", "code": "loopback_only"},
                status_code=403,
            )

        origin = (request.headers.get("Origin") or "").strip().rstrip("/")
        allowed = _allowed_origins()
        if origin and origin not in allowed:
            return JSONResponse(
                {
                    "status": "error",
                    "code": "origin_not_allowed",
                    "message": (
                        "Add this exact frontend origin to "
                        "REVELAAI_AUTOMATION_ALLOWED_ORIGINS to enable browser access."
                    ),
                },
                status_code=403,
            )

        if request.method == "OPTIONS":
            if not origin or origin not in allowed:
                return JSONResponse(
                    {"status": "error", "code": "origin_not_allowed"},
                    status_code=403,
                )
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Vary": "Origin",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Max-Age": "300",
                },
            )

        response = await call_next(request)
        if origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the loopback-only RevelaAI Automation Fabric local agent."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Only 127.0.0.1 is permitted.")
    parser.add_argument("--port", type=int, default=38741)
    parser.add_argument(
        "--show-token",
        action="store_true",
        help="Print the local bearer token for deliberate manual setup.",
    )
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
    uvicorn.run(
        create_local_app(token),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
