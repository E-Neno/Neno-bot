from fastapi import APIRouter, Depends

from app.security import require_admin_token
from app.services.stats_service import get_stats_summary

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", dependencies=[Depends(require_admin_token)])
def stats_summary():
    return {
        "success": True,
        "summary": get_stats_summary(),
    }
