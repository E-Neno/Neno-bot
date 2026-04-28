from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.schemas import (
    ProactiveConfigUpdateRequest,
    ProactiveDismissRequest,
    ProactiveGenerateRequest,
    ProactiveGenerateTestRequest,
    ProactiveRunOnceRequest,
    ProactiveSendQqRequest,
)
from app.security import require_admin_token
from app.services.proactive_config_service import get_proactive_config, update_proactive_config
from app.services.proactive_scheduler import (
    check_proactive_now,
    get_proactive_scheduler_status,
    run_proactive_once_manual,
)
from app.services.proactive_service import (
    generate_proactive_candidate,
    generate_test_proactive_candidate,
    get_recent_proactive_candidates,
    get_recent_proactive_events,
    get_recent_proactive_targets,
    sanitize_proactive_candidate,
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


@router.get("/targets", dependencies=[Depends(require_admin_token)])
def proactive_targets():
    return {
        "success": True,
        "targets": get_recent_proactive_targets(limit=20),
    }


@router.get("/events", dependencies=[Depends(require_admin_token)])
def proactive_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None, max_length=64),
):
    return {
        "success": True,
        "events": get_recent_proactive_events(limit=limit, event_type=event_type),
    }


@router.post("/check-now", dependencies=[Depends(require_admin_token)])
def proactive_check_now():
    return check_proactive_now()


@router.post("/run-once", dependencies=[Depends(require_admin_token)])
def proactive_run_once(req: ProactiveRunOnceRequest | None = Body(default=None)):
    options = req or ProactiveRunOnceRequest()
    return run_proactive_once_manual(
        ignore_random=options.ignore_random,
        ignore_recent_chat=options.ignore_recent_chat,
        ignore_active_window=options.ignore_active_window,
        force=options.force,
        dry_run_only=options.dry_run_only,
    )


@router.get("/config", dependencies=[Depends(require_admin_token)])
def proactive_config():
    return get_proactive_config()


@router.post("/config", dependencies=[Depends(require_admin_token)])
def proactive_config_update(req: ProactiveConfigUpdateRequest):
    return update_proactive_config(req)


@router.post("/generate", dependencies=[Depends(require_admin_token)])
def proactive_generate(req: ProactiveGenerateRequest | None = Body(default=None)):
    return generate_proactive_candidate(platform=req.platform if req else None)


@router.post("/generate-test", dependencies=[Depends(require_admin_token)])
def proactive_generate_test(req: ProactiveGenerateTestRequest | None = Body(default=None)):
    return generate_test_proactive_candidate(force=req.force if req else False)


@router.post("/dismiss", dependencies=[Depends(require_admin_token)])
def proactive_dismiss(req: ProactiveDismissRequest):
    candidate = update_proactive_candidate_status(req.id, "dismissed")
    if candidate is None:
        raise HTTPException(status_code=404, detail="proactive candidate not found")
    return {
        "success": True,
        "candidate": sanitize_proactive_candidate(candidate),
    }


@router.post("/send-qq", dependencies=[Depends(require_admin_token)])
def proactive_send_qq(req: ProactiveSendQqRequest):
    return send_qq_candidate(candidate_id=req.id, dry_run=req.dry_run)
