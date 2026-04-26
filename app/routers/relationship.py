from fastapi import APIRouter, Depends

from app.schemas import RelationshipUpdateRequest, SessionRequest
from app.security import require_admin_token
from app.services.relationship_service import (
    get_relationship_state_for_api,
    reset_relationship_state_for_api,
    update_relationship_state_manual_for_api,
)

router = APIRouter(prefix="/relationship", tags=["relationship"])


@router.get("/state")
def get_state(session_id: str = "default"):
    return get_relationship_state_for_api(session_id)


@router.post("/reset")
def reset_state(req: SessionRequest, _: None = Depends(require_admin_token)):
    return reset_relationship_state_for_api(req.session_id)


@router.post("/update")
def update_state(req: RelationshipUpdateRequest, _: None = Depends(require_admin_token)):
    updates = req.model_dump(exclude_unset=True)
    session_id = updates.pop("session_id")
    return update_relationship_state_manual_for_api(session_id, updates)
