from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import CHAT_MODEL_NAME, HISTORY_TOKEN_LIMIT, MEMORY_LIMIT, MEMORY_MODEL_NAME
from app.schemas import ConfigUpdateRequest
from app.security import require_admin_token
from app.utils.env_writer import update_env_file

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ALLOWED_CONFIG_KEYS = {
    "chat_model": "OPENROUTER_CHAT_MODEL",
    "memory_model": "OPENROUTER_MEMORY_MODEL",
    "history_token_limit": "HISTORY_TOKEN_LIMIT",
    "memory_limit": "MEMORY_LIMIT",
}


@router.get("/")
def root():
    return {"status": "ok"}


@router.get("/config")
def get_config():
    return {
        "success": True,
        "chat_model": CHAT_MODEL_NAME,
        "memory_model": MEMORY_MODEL_NAME,
        "history_token_limit": HISTORY_TOKEN_LIMIT,
        "memory_limit": MEMORY_LIMIT,
    }


@router.post("/config/update", dependencies=[Depends(require_admin_token)])
def update_config(req: ConfigUpdateRequest):
    updates: dict[str, str] = {}

    if req.chat_model is not None:
        chat_model = req.chat_model.strip()
        if not chat_model:
            raise HTTPException(status_code=400, detail="chat_model must not be empty")
        updates[ALLOWED_CONFIG_KEYS["chat_model"]] = chat_model

    if req.memory_model is not None:
        memory_model = req.memory_model.strip()
        if not memory_model:
            raise HTTPException(status_code=400, detail="memory_model must not be empty")
        updates[ALLOWED_CONFIG_KEYS["memory_model"]] = memory_model

    if req.history_token_limit is not None:
        if not 50 <= req.history_token_limit <= 5000:
            raise HTTPException(status_code=400, detail="history_token_limit must be between 50 and 5000")
        updates[ALLOWED_CONFIG_KEYS["history_token_limit"]] = str(req.history_token_limit)

    if req.memory_limit is not None:
        if not 0 <= req.memory_limit <= 20:
            raise HTTPException(status_code=400, detail="memory_limit must be between 0 and 20")
        updates[ALLOWED_CONFIG_KEYS["memory_limit"]] = str(req.memory_limit)

    if not updates:
        raise HTTPException(status_code=400, detail="no valid config fields provided")

    try:
        updated = update_env_file(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "config updated, run nereboot to apply changes",
        "updated": updated,
        "need_restart": True,
    }


@router.get("/test")
def test_page():
    return FileResponse(STATIC_DIR / "test.html")
