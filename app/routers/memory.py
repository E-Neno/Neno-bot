from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas import (
    MemoryActionRequest,
    MemoryAddRequest,
    MemoryAddResponse,
    MemoryDisableRequest,
    MemoryDisableResponse,
    MemoryUpdateRequest,
)
from app.security import require_admin_token
from app.services.memory_service import find_similar_memories, get_relevant_memories
from app.storage.db import (
    add_memory,
    delete_memory,
    get_all_memories,
    get_memories_by_status,
    memory_exists,
    set_memory_active,
    update_memory,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/add", response_model=MemoryAddResponse, dependencies=[Depends(require_admin_token)])
def memory_add(req: MemoryAddRequest):
    try:
        add_memory(req.content, req.memory_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MemoryAddResponse(success=True, message=f"记忆已添加：{req.content}")


@router.post("/delete", dependencies=[Depends(require_admin_token)])
def memory_delete(req: MemoryActionRequest):
    try:
        ok = delete_memory(req.id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")

    return {
        "success": True,
        "message": f"memory {req.id} deleted",
    }


@router.post("/update", dependencies=[Depends(require_admin_token)])
def memory_update(req: MemoryUpdateRequest):
    try:
        memory = update_memory(req.id, req.content, req.memory_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")

    return {
        "success": True,
        "message": f"memory {req.id} updated",
        "memory": memory,
    }


@router.get("/list", dependencies=[Depends(require_admin_token)])
def memory_list(active: int | None = Query(default=None)):
    memories = get_all_memories() if active is None else get_memories_by_status(active)
    return {"success": True, "memories": memories}


@router.get("/relevant", dependencies=[Depends(require_admin_token)])
def memory_relevant(
    query: str = Query(..., min_length=1, max_length=2000),
    limit: int = Query(default=5, ge=1, le=50),
):
    memories = get_relevant_memories(query=query, limit=limit)
    return {
        "success": True,
        "query": query,
        "count": len(memories),
        "memories": memories,
    }


@router.post("/disable", response_model=MemoryDisableResponse, dependencies=[Depends(require_admin_token)])
def memory_disable(req: MemoryDisableRequest):
    try:
        ok = set_memory_active(req.memory_id, False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")

    return MemoryDisableResponse(success=True, message=f"记忆已停用：id={req.memory_id}")


@router.post("/enable", dependencies=[Depends(require_admin_token)])
def memory_enable(req: MemoryActionRequest):
    ok = set_memory_active(req.id, True)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"success": True, "message": f"memory {req.id} enabled"}


@router.post("/confirm", dependencies=[Depends(require_admin_token)])
def memory_confirm(req: MemoryAddRequest):
    try:
        if memory_exists(req.content):
            return {
                "success": True,
                "message": "memory already exists",
                "content": req.content,
                "memory_type": req.memory_type,
            }

        add_memory(req.content, req.memory_type)
        duplicate_candidates = find_similar_memories(
            content=req.content,
            memory_type=req.memory_type,
            limit=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "success": True,
        "message": "candidate memory saved",
        "content": req.content,
        "memory_type": req.memory_type,
        "duplicate_candidates": duplicate_candidates,
    }
