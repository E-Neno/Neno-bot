from fastapi import Header, HTTPException, Request

from app.config import ADMIN_TOKEN, PLATFORM_TOKEN

LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost"}


def require_admin_token(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="ADMIN_TOKEN not configured")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="invalid admin token")


def is_loopback_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOOPBACK_CLIENTS


def require_platform_token(
    request: Request,
    x_platform_token: str | None = Header(default=None),
):
    # Local bypass is only for the OpenClaw bridge on the same host.
    if is_loopback_client(request):
        return
    if not PLATFORM_TOKEN:
        raise HTTPException(status_code=403, detail="PLATFORM_TOKEN not configured")
    if x_platform_token != PLATFORM_TOKEN:
        raise HTTPException(status_code=403, detail="invalid platform token")
