from fastapi import APIRouter, Depends, Query

from app.schemas import SessionRequest
from app.security import require_admin_token
from app.storage.db import clear_session_messages, get_session_messages, get_sessions

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/messages", dependencies=[Depends(require_admin_token)])
def session_messages(
    session_id: str = Query(default="default", max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
):
    messages = get_session_messages(session_id=session_id, limit=limit)
    return {
        "success": True,
        "session_id": session_id,
        "count": len(messages),
        "messages": messages,
    }


@router.get("/list", dependencies=[Depends(require_admin_token)])
def session_list():
    sessions = get_sessions()
    return {
        "success": True,
        "count": len(sessions),
        "sessions": sessions,
    }


@router.post("/clear", dependencies=[Depends(require_admin_token)])
def session_clear(req: SessionRequest):
    deleted = clear_session_messages(req.session_id)
    return {
        "success": True,
        "session_id": req.session_id,
        "deleted": deleted,
        "message": f"已清空会话：{req.session_id}",
    }
