import json as _json
import logging as _logging
from typing import Any

from fastapi import HTTPException

from app.config import (
    PROACTIVE_AUTO_SEND_MAX_PER_DAY,
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
)
from app.services.proactive.result_helpers import (
    generated_pending_result,
    now_iso,
    update_candidate_metadata,
)
from app.services.proactive.rules import today_auto_sent_count
from app.services.proactive_service import (
    _mask_identifier,
    _target_hash_for_session,
    is_allowed_qq_target,
    record_proactive_event,
    send_proactive_candidate,
)
from app.storage.db import (
    add_debug_event,
    add_proactive_candidate,
    execute_write,
    get_proactive_target_by_session,
    update_proactive_candidate_status,
)
from app.utils.logging_utils import log_event


def record_auto_send_error(candidate_id: int, action: str, error: str) -> None:
    update_candidate_metadata(
        candidate_id,
        {
            "auto_send_error": (error or "auto send failed")[:160],
            "auto_send_failed_at": now_iso(),
            "auto_send_action": action,
        },
    )


def candidate_can_auto_send(candidate: dict, target_row: dict[str, Any]) -> tuple[bool, str | None]:
    platform = str(candidate.get("platform") or "").strip().lower()
    if platform not in {"qq", "wx"}:
        return False, "auto send only supports qq or wx"
    if candidate.get("status") != "pending":
        return False, "candidate is not pending"
    if platform == "qq":
        if int(target_row.get("is_allowed") or 0) != 1:
            return False, "target is not allowed"
        if PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET and not is_allowed_qq_target(str(candidate.get("target_hash") or "")):
            return False, "target is not allowed"
    else:
        if not str(target_row.get("real_user_id") or "").strip():
            return False, "wx real target is missing"
    auto_sent_today = today_auto_sent_count()
    if auto_sent_today >= PROACTIVE_AUTO_SEND_MAX_PER_DAY:
        return False, f"auto send max per day reached: {PROACTIVE_AUTO_SEND_MAX_PER_DAY}"
    return True, None


def auto_send_dry_run(
    candidate: dict,
    *,
    event_source: str = "auto",
    trace_id: str | None = None,
) -> dict[str, Any]:
    platform = str(candidate.get("platform") or "").strip().lower() or None
    try:
        send_proactive_candidate(
            candidate_id=candidate["id"],
            dry_run=True,
            event_source=event_source,
            trace_id=trace_id,
        )
    except HTTPException as exc:
        record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", str(exc.detail))
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform=platform,
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
            reason=str(exc.detail),
        )
        log_event(
            "proactive",
            "proactive_dry_run_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_dry_run_failed",
            dry_run=True,
            success=False,
            reason=str(exc.detail),
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_dry_run_failed",
            "candidate_id": candidate["id"],
            "error": str(exc.detail),
        }
    except Exception as exc:
        record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", type(exc).__name__)
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform=platform,
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        log_event(
            "proactive",
            "proactive_dry_run_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_dry_run_failed",
            dry_run=True,
            success=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_dry_run_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    update_candidate_metadata(
        candidate["id"],
        {
            "auto_send_dry_run": True,
            "auto_send_dry_run_at": now_iso(),
            "auto_send_action": "auto_send_dry_run_ok",
        },
    )
    record_proactive_event(
        event_type="auto_send_dry_run",
        platform=platform,
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_send_dry_run_ok",
        success=True,
        skipped=False,
    )
    log_event(
        "proactive",
        "proactive_dry_run_ok",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="auto_send_dry_run_ok",
        dry_run=True,
        success=True,
    )
    return {
        "success": True,
        "skipped": False,
        "action": "auto_send_dry_run_ok",
        "candidate_id": candidate["id"],
        "platform": platform,
        "target_label": candidate.get("target_label"),
    }


def auto_send_real(
    candidate: dict,
    target_row: dict[str, Any],
    trace_id: str | None = None,
) -> dict[str, Any]:
    platform = str(candidate.get("platform") or "").strip().lower() or None
    can_send, blocked_reason = candidate_can_auto_send(candidate, target_row)
    if not can_send:
        update_candidate_metadata(
            candidate["id"],
            {
                "auto_send_blocked": True,
                "auto_send_blocked_at": now_iso(),
                "auto_send_blocked_reason": blocked_reason,
            },
        )
        result = generated_pending_result(candidate, blocked_reason)
        result["platform"] = platform
        return result

    try:
        send_proactive_candidate(
            candidate_id=candidate["id"],
            dry_run=False,
            event_source="auto",
            trace_id=trace_id,
        )
    except HTTPException as exc:
        record_auto_send_error(candidate["id"], "auto_send_failed", str(exc.detail))
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform=platform,
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
            reason=str(exc.detail),
        )
        log_event(
            "proactive",
            "proactive_auto_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_failed",
            dry_run=False,
            auto_send=True,
            success=False,
            reason=str(exc.detail),
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_failed",
            "candidate_id": candidate["id"],
            "error": str(exc.detail),
        }
    except Exception as exc:
        record_auto_send_error(candidate["id"], "auto_send_failed", type(exc).__name__)
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform=platform,
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        log_event(
            "proactive",
            "proactive_auto_failed",
            trace_id=trace_id,
            candidate_id=candidate.get("id"),
            target_label=candidate.get("target_label"),
            action="auto_send_failed",
            dry_run=False,
            auto_send=True,
            success=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    update_candidate_metadata(
        candidate["id"],
        {
            "auto_sent": True,
            "auto_sent_at": now_iso(),
            "auto_send_action": "auto_sent",
        },
    )
    record_proactive_event(
        event_type="auto_sent",
        platform=platform,
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_sent",
        success=True,
        skipped=False,
    )
    log_event(
        "proactive",
        "proactive_auto_sent",
        trace_id=trace_id,
        candidate_id=candidate.get("id"),
        target_label=candidate.get("target_label"),
        action="auto_sent",
        dry_run=False,
        auto_send=True,
        success=True,
    )
    return {
        "success": True,
        "skipped": False,
        "sent": True,
        "action": "auto_sent",
        "candidate_id": candidate["id"],
        "platform": platform,
        "target_label": candidate.get("target_label"),
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 3b: Brain Intent 发送（不改上方现有函数）
# ──────────────────────────────────────────────────────────────────────

_logger = _logging.getLogger(__name__)


def send_brain_intent(
    user_id: str,
    fragments: list[str],
    trace_id: str,
    intent_id: int,
) -> dict:
    """
    将 brain 生成的 fragments 逐条转写为 proactive_candidates（source='brain'），
    调用现有 send_proactive_candidate() 复用微信发送链路。

    每条 fragment 独立创建一个 candidate → 独立发送 → 独立落库。
    一旦开始发送，完成全部 fragments（原子发送，不腰斩）。

    target 通过 get_proactive_target_by_session 精确查找，
    禁止用 get_latest_proactive_target 取"最新目标"，避免发错人。

    返回: {"success": bool, "sent_count": int, "total": int, "error": str|None}
    """
    # ── 提取 platform 和 session_id ──
    parts = (user_id or "").split(":")
    platform = parts[0] if parts else ""
    session_id = user_id  # user_id 本身就是 session_id 格式

    if not platform or not session_id:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        add_debug_event(
            trace_id=trace_id,
            module="send_brain_intent",
            event="invalid_user_id",
            level="error",
            reason=f"user_id format invalid: {user_id}",
            action="dropped",
        )
        return {"success": False, "sent_count": 0, "total": len(fragments), "error": "invalid user_id"}

    # ── 精确查 proactive_targets ──
    target_row = get_proactive_target_by_session(platform, session_id)
    if not target_row:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        add_debug_event(
            trace_id=trace_id,
            module="send_brain_intent",
            event="no_target",
            level="warning",
            reason=f"no {platform} target for session {session_id}",
            action="dropped",
        )
        _logger.warning(
            "[%s] brain intent dropped: no %s target for session %s",
            trace_id, platform, session_id,
        )
        return {"success": False, "sent_count": 0, "total": len(fragments), "error": "no target for session"}

    # ── 从 target_row 提取发送所需字段 ──
    real_user_id = str(target_row.get("real_user_id") or "").strip()
    target_hash = _target_hash_for_session(session_id)
    target_label = _mask_identifier(real_user_id or "")
    permission_uid = parts[2] if len(parts) >= 3 else ""

    # ── 构造 candidate metadata（_resolve_wx_candidate_target 需要） ──
    base_metadata = {
        "session_id": session_id,
        "wx_real_user_id": real_user_id or None,
        "wx_permission_user_id": permission_uid,
        "source": "brain",
        "brain_intent_id": intent_id,
        "brain_trace_id": trace_id,
    }

    # ── 逐条 fragment 发送（原子，不腰斩） ──
    sent_count = 0
    error_msg = None

    for idx, fragment in enumerate(fragments):
        fragment = (fragment or "").strip()
        if not fragment:
            continue

        meta = {
            **base_metadata,
            "brain_fragment_index": idx,
            "brain_fragment_count": len(fragments),
        }

        try:
            candidate = add_proactive_candidate(
                platform=platform,
                target_hash=target_hash,
                target_label=target_label,
                message=fragment,
                reason=f"brain intent #{intent_id} frag {idx}",
                status="pending",
                source="brain",
                metadata_json=_json.dumps(meta, ensure_ascii=False),
            )
        except Exception as e:
            error_msg = f"candidate_create_failed: {e}"[:200]
            add_debug_event(
                trace_id=trace_id,
                module="send_brain_intent",
                event="candidate_create_failed",
                level="error",
                reason=error_msg,
                action="send_failed",
            )
            _logger.error(
                "[%s] brain intent fragment %d candidate create failed: %s",
                trace_id, idx, e,
            )
            break

        try:
            send_proactive_candidate(
                candidate_id=candidate["id"],
                dry_run=False,
                event_source="brain",
                trace_id=trace_id,
            )
            sent_count += 1
            _logger.info(
                "[%s] brain intent #%d frag %d/%d sent (candidate %d)",
                trace_id, intent_id, idx + 1, len(fragments), candidate["id"],
            )
        except Exception as e:
            error_msg = str(e)[:200]
            add_debug_event(
                trace_id=trace_id,
                module="send_brain_intent",
                event="fragment_send_failed",
                level="error",
                reason=error_msg,
                action="send_failed",
            )
            _logger.error(
                "[%s] brain intent #%d frag %d send failed: %s",
                trace_id, intent_id, idx, e,
            )
            break

    # ── 更新 proactive_intent status ──
    if sent_count == len(fragments):
        status = "sent"
    elif sent_count > 0:
        status = "partial"
    else:
        status = "dropped"

    execute_write(
        "UPDATE proactive_intent SET status=? WHERE id=?",
        (status, intent_id),
    )

    _logger.info(
        "[%s] brain intent #%d result: status=%s sent=%d/%d error=%s",
        trace_id, intent_id, status, sent_count, len(fragments), error_msg,
    )

    return {
        "success": sent_count > 0,
        "sent_count": sent_count,
        "total": len(fragments),
        "error": error_msg,
    }


def send_world_expression(
    session_id: str,
    fragments: list[str],
    trace_id: str,
    *,
    dry_run: bool = True,
) -> dict:
    """把她「醒来/空了」补的回复经 proactive 发送链路推回平台（WX/QQ）。

    复用 send_brain_intent 的发送链路（精确按 session 查 target → add_proactive_candidate →
    send_proactive_candidate），但 source='world'、不耦合 proactive_intent。
    dry_run=True 时建候选+演练不真发（默认安全）；真发由上层 WORLD_PRESENCE_WX_AUTO_SEND 控制。
    target 精确按 session 查，禁止取「最新目标」以免发错人。
    """
    parts = (session_id or "").split(":")
    platform = parts[0] if parts else ""
    valid_frags = [(f or "").strip() for f in fragments if (f or "").strip()]
    if not platform or not session_id:
        return {"success": False, "sent_count": 0, "total": len(valid_frags), "error": "invalid session_id"}

    target_row = get_proactive_target_by_session(platform, session_id)
    if not target_row:
        add_debug_event(
            trace_id=trace_id, module="send_world_expression", event="no_target",
            level="warning", reason=f"no {platform} target for session {session_id}", action="dropped",
        )
        return {"success": False, "sent_count": 0, "total": len(valid_frags), "error": "no target for session"}

    real_user_id = str(target_row.get("real_user_id") or "").strip()
    target_hash = _target_hash_for_session(session_id)
    target_label = _mask_identifier(real_user_id or "")
    permission_uid = parts[2] if len(parts) >= 3 else ""
    base_metadata = {
        "session_id": session_id,
        "wx_real_user_id": real_user_id or None,
        "wx_permission_user_id": permission_uid,
        "source": "world",
        "world_trace_id": trace_id,
    }

    sent_count = 0
    error_msg = None
    for idx, fragment in enumerate(valid_frags):
        meta = {**base_metadata, "world_fragment_index": idx, "world_fragment_count": len(valid_frags)}
        try:
            candidate = add_proactive_candidate(
                platform=platform, target_hash=target_hash, target_label=target_label,
                message=fragment, reason=f"world pending pickup ({'dry_run' if dry_run else 'send'})",
                status="pending", source="world",
                metadata_json=_json.dumps(meta, ensure_ascii=False),
            )
        except Exception as e:  # noqa: BLE001
            error_msg = f"candidate_create_failed: {e}"[:200]
            break
        try:
            send_proactive_candidate(
                candidate_id=candidate["id"], dry_run=dry_run,
                event_source="world", trace_id=trace_id,
            )
            sent_count += 1
        except Exception as e:  # noqa: BLE001
            error_msg = str(e)[:200]
            break

    return {
        "success": sent_count == len(valid_frags) and bool(valid_frags),
        "sent_count": sent_count,
        "total": len(valid_frags),
        "error": error_msg,
        "dry_run": dry_run,
    }
