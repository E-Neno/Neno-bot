from fastapi import APIRouter, Query

from app.services.time_context_service import build_time_context

router = APIRouter(prefix="/context", tags=["context"])


@router.get("/time")
def time_context(session_id: str = Query(default="default", max_length=128)):
    return build_time_context(session_id)
