import time

from fastapi import APIRouter, HTTPException

from app.schemas import ChatRequest, ChatResponse
from app.services.chat_service import run_chat_turn
from app.services.stats_service import record_chat_stat

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    started = time.perf_counter()
    try:
        result = run_chat_turn(req.session_id, req.message)
    except RuntimeError as exc:
        record_chat_stat(
            source="web",
            platform="web",
            session_id=req.session_id,
            message=req.message,
            reply="",
            success=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        record_chat_stat(
            source="web",
            platform="web",
            session_id=req.session_id,
            message=req.message,
            reply="",
            success=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )
        raise

    record_chat_stat(
        source="web",
        platform="web",
        session_id=req.session_id,
        message=req.message,
        reply=result["reply"],
        success=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )

    return ChatResponse(
        reply=result["reply"],
        candidate_memory=result["candidate_memory"],
        candidate_memory_decision=result["candidate_memory_decision"],
        auto_added=result["auto_added"],
        auto_added_memory=result["auto_added_memory"],
        used_memories=result["used_memories"],
        relationship_state=result["relationship_state"],
        relationship_context=result["relationship_context"],
    )
