from fastapi import APIRouter, Body, Depends, HTTPException

from app.schemas import (
    ProactiveConfigUpdateRequest,
    ProactiveDismissRequest,
    ProactiveGenerateRequest,
    ProactiveSendQqRequest,
)
from app.security import require_admin_token
from app.services.proactive_config_service import get_proactive_config, update_proactive_config
from app.services.proactive_scheduler import get_proactive_scheduler_status
from app.services.proactive_service import (
    generate_proactive_candidate,
    get_recent_proactive_candidates,
    send_qq_candidate,
)
from app.storage.db import update_proactive_candidate_status

router = APIRouter(prefix="/proactive", tags=["proactive"])


@router.get("/candidates", dependencies=[Depends(require_admin_token)])
def proactive_candidates():
    return {
        "success": True,
        "candidates": get_recent_proactive_candidates(limit=20),
    }


@router.get("/status", dependencies=[Depends(require_admin_token)])
def proactive_status():
    return get_proactive_scheduler_status()


@router.get("/config", dependencies=[Depends(require_admin_token)])
def proactive_config():
    return get_proactive_config()


@router.post("/config", dependencies=[Depends(require_admin_token)])
def proactive_config_update(req: ProactiveConfigUpdateRequest):
    return update_proactive_config(req)


@router.post("/generate", dependencies=[Depends(require_admin_token)])
def proactive_generate(req: ProactiveGenerateRequest | None = Body(default=None)):
    return generate_proactive_candidate(platform=req.platform if req else None)


@router.post("/dismiss", dependencies=[Depends(require_admin_token)])
def proactive_dismiss(req: ProactiveDismissRequest):
    candidate = update_proactive_candidate_status(req.id, "dismissed")
    if candidate is None:
        raise HTTPException(status_code=404, detail="proactive candidate not found")
    return {
        "success": True,
        "candidate": candidate,
    }


@router.post("/send-qq", dependencies=[Depends(require_admin_token)])
def proactive_send_qq(req: ProactiveSendQqRequest):
    return send_qq_candidate(candidate_id=req.id, dry_run=req.dry_run)
