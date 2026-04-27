import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from app.config import (
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_END_TIME,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_ACTIVE_START_TIME,
    PROACTIVE_AUTO_SEND,
    PROACTIVE_AUTO_SEND_DRY_RUN,
    PROACTIVE_AUTO_SEND_MAX_PER_DAY,
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
    PROACTIVE_CHECK_INTERVAL_SECONDS,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_ENABLED,
    PROACTIVE_MIN_INTERVAL_MINUTES,
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES,
    PROACTIVE_RANDOM_PROBABILITY,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.services.proactive_service import (
    SAFE_TEMPLATES,
    _mask_hash,
    is_allowed_qq_target,
    record_proactive_event,
    send_qq_candidate,
)
from app.storage.db import (
    add_proactive_candidate,
    fetch_one,
    get_proactive_candidate,
    get_latest_allowed_proactive_target,
    update_proactive_candidate_metadata,
    update_proactive_candidate_status,
)

_scheduler_task: asyncio.Task | None = None
_last_check_at: str | None = None
_last_result: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_sqlite_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _within_active_window(now: datetime) -> bool:
    current = now.time()
    if PROACTIVE_ACTIVE_START_TIME <= PROACTIVE_ACTIVE_END_TIME:
        return PROACTIVE_ACTIVE_START_TIME <= current <= PROACTIVE_ACTIVE_END_TIME
    return current >= PROACTIVE_ACTIVE_START_TIME or current <= PROACTIVE_ACTIVE_END_TIME


def _today_sent_count() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND source = 'auto'
          AND status = 'sent'
          AND date(created_at, 'localtime') = date('now', 'localtime')
        """
    )
    return int(row["count"] or 0) if row else 0


def _today_auto_sent_count() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND source = 'auto'
          AND status = 'sent'
          AND date(created_at, 'localtime') = date('now', 'localtime')
          AND metadata_json LIKE '%"auto_sent": true%'
        """
    )
    return int(row["count"] or 0) if row else 0


def _last_sent_at() -> str | None:
    row = fetch_one(
        """
        SELECT created_at
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND source = 'auto'
          AND status = 'sent'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    return str(row["created_at"]) if row else None


def _has_recent_user_message() -> bool:
    row = fetch_one(
        f"""
        SELECT 1 AS found
        FROM chat_stats
        WHERE platform = 'qq'
          AND created_at >= datetime('now', '-{PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes')
        LIMIT 1
        """
    )
    return row is not None


def _has_pending_qq_candidate() -> bool:
    row = fetch_one(
        """
        SELECT 1 AS found
        FROM proactive_candidates
        WHERE platform = 'qq'
          AND status = 'pending'
        LIMIT 1
        """
    )
    return row is not None


def _latest_qq_target() -> dict[str, Any] | None:
    return get_latest_allowed_proactive_target("qq")


def _skip(reason: str) -> dict[str, Any]:
    record_proactive_event(
        event_type="rule_skipped",
        platform="qq",
        action="skipped",
        success=True,
        skipped=True,
        reason=reason,
    )
    return {
        "success": True,
        "skipped": True,
        "reason": reason,
    }


def explain_proactive_reason(reason: str | None) -> str:
    text = str(reason or "").strip()
    lower = text.lower()
    if not text:
        return ""
    if "random probability missed" in lower:
        return "随机概率未命中，本轮不发送"
    if "outside active window" in lower:
        return "不在允许主动消息的时间段"
    if "recent chat exists" in lower or "user message seen within" in lower:
        return "最近刚聊过，跳过主动消息"
    if "daily sent limit reached" in lower or "daily limit reached" in lower:
        return "今天主动消息已达到上限"
    if "last sent is within" in lower or "min interval not reached" in lower:
        return "距离上次主动消息还不够久"
    if "pending qq candidate exists" in lower or "pending candidate exists" in lower:
        return "已有待处理候选，暂不生成新的"
    if "not whitelisted" in lower:
        return "最新 QQ 目标不在白名单，暂不发送"
    if "no allowed qq target" in lower or "no qq target" in lower:
        return "没有可用 QQ 主动目标，请先给机器人发一条 QQ 消息，并在主动目标中允许该目标。"
    if "disabled" in lower:
        return "自动主动消息未开启"
    return text


def _with_explained_reason(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    normalized = dict(result)
    if "reason" in normalized:
        normalized["reason"] = explain_proactive_reason(str(normalized.get("reason") or ""))
    if "error" in normalized and "reason" not in normalized:
        normalized["reason"] = explain_proactive_reason(str(normalized.get("error") or "发送失败"))
    return normalized


def _load_candidate_metadata(candidate: dict | None) -> dict[str, Any]:
    if not candidate:
        return {}
    raw = candidate.get("metadata_json") or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _update_candidate_metadata(candidate_id: int, updates: dict[str, Any]) -> dict | None:
    candidate = get_proactive_candidate(candidate_id)
    metadata = _load_candidate_metadata(candidate)
    metadata.update(updates)
    return update_proactive_candidate_metadata(
        candidate_id,
        json.dumps(metadata, ensure_ascii=False),
    )


def _rule(name: str, ok: bool | None, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
    }


def _next_rules_summary() -> list[str]:
    return [
        "自动主动消息已开启" if PROACTIVE_ENABLED else "自动主动消息未开启",
        "当前只支持 QQ",
        f"每天最多 {PROACTIVE_DAILY_LIMIT} 条",
        f"两次主动消息至少间隔 {PROACTIVE_MIN_INTERVAL_MINUTES} 分钟",
        f"最近 {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} 分钟聊过则跳过",
        f"活跃时间段 {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
        f"每次检查随机概率 {PROACTIVE_RANDOM_PROBABILITY}",
        "自动真实发送已开启" if PROACTIVE_AUTO_SEND else "自动调度只生成 pending 候选",
        "自动发送 dry_run 模式" if PROACTIVE_AUTO_SEND_DRY_RUN else "自动发送 dry_run 未开启",
        f"自动真实发送每天最多 {PROACTIVE_AUTO_SEND_MAX_PER_DAY} 条",
    ]


def evaluate_proactive_rules(*, include_enabled: bool = True) -> dict[str, Any]:
    now = datetime.now()
    checks: list[dict[str, Any]] = []

    if include_enabled:
        checks.append(
            _rule(
                "enabled",
                PROACTIVE_ENABLED,
                "自动主动消息已开启" if PROACTIVE_ENABLED else "自动主动消息未开启",
            )
        )

    active_ok = _within_active_window(now)
    checks.append(
        _rule(
            "active_window",
            active_ok,
            f"当前时间 {'在' if active_ok else '不在'}允许主动消息时间段 {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
        )
    )

    sent_count = _today_sent_count()
    daily_ok = sent_count < PROACTIVE_DAILY_LIMIT
    checks.append(
        _rule(
            "daily_limit",
            daily_ok,
            f"今天已自动发送 {sent_count}/{PROACTIVE_DAILY_LIMIT} 条",
        )
    )

    last_sent_raw = _last_sent_at()
    last_sent = _parse_sqlite_datetime(last_sent_raw)
    min_interval_ok = last_sent is None or now - last_sent >= timedelta(minutes=PROACTIVE_MIN_INTERVAL_MINUTES)
    if last_sent is None:
        min_interval_detail = "还没有自动主动消息发送记录"
    else:
        elapsed_minutes = int((now - last_sent).total_seconds() // 60)
        min_interval_detail = f"距离上次自动主动消息约 {elapsed_minutes} 分钟，要求至少 {PROACTIVE_MIN_INTERVAL_MINUTES} 分钟"
    checks.append(_rule("min_interval", min_interval_ok, min_interval_detail))

    recent_chat = _has_recent_user_message()
    checks.append(
        _rule(
            "recent_chat",
            not recent_chat,
            f"最近 {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} 分钟{'有' if recent_chat else '没有'} QQ 用户消息",
        )
    )

    pending_candidate = _has_pending_qq_candidate()
    checks.append(
        _rule(
            "pending_candidate",
            not pending_candidate,
            "已有待处理 QQ 候选" if pending_candidate else "没有待处理 QQ 候选",
        )
    )

    target_row = _latest_qq_target()
    target_hash = str(target_row["target_hash"] or "") if target_row else ""
    checks.append(
        _rule(
            "qq_target",
            target_row is not None,
            f"最近 QQ 目标 {_mask_hash(target_hash)}" if target_row else "没有找到 QQ 目标",
        )
    )

    whitelist_ok = bool(target_hash) and is_allowed_qq_target(target_hash)
    checks.append(
        _rule(
            "qq_whitelist",
            whitelist_ok,
            "最近 QQ 目标在白名单内" if whitelist_ok else "最近 QQ 目标不在白名单内",
        )
    )

    target_allowed = bool(target_row and int(target_row.get("is_allowed") or 0) == 1)
    checks.append(
        _rule(
            "allowed_target",
            target_allowed,
            "自动目标已 allowed" if target_allowed else "自动目标未 allowed",
        )
    )

    checks.append(
        _rule(
            "auto_send_enabled",
            None,
            "自动真实发送已开启" if PROACTIVE_AUTO_SEND else "自动真实发送关闭：命中后只生成 pending candidate",
        )
    )
    checks.append(
        _rule(
            "auto_send_dry_run",
            None,
            "自动发送 dry_run 开启：只测试发送链路" if PROACTIVE_AUTO_SEND_DRY_RUN else "自动发送 dry_run 关闭",
        )
    )
    auto_sent_today = _today_auto_sent_count()
    auto_send_limit_ok = auto_sent_today < PROACTIVE_AUTO_SEND_MAX_PER_DAY
    checks.append(
        _rule(
            "auto_send_max_per_day",
            auto_send_limit_ok if PROACTIVE_AUTO_SEND and not PROACTIVE_AUTO_SEND_DRY_RUN else None,
            f"今天自动真实发送 {auto_sent_today}/{PROACTIVE_AUTO_SEND_MAX_PER_DAY} 条",
        )
    )

    checks.append(_rule("random_probability", None, "check-now 不掷随机数"))

    first_failed = next((check for check in checks if check["ok"] is False), None)
    can_send = first_failed is None
    reason = "当前规则允许发送；正式调度仍会再判断随机概率" if can_send else str(first_failed["detail"])

    return {
        "can_send": can_send,
        "reason": reason,
        "checks": checks,
    }


def _create_auto_candidate(target_row: dict[str, Any]) -> dict:
    target_hash = str(target_row["target_hash"] or "")
    session_id = str(target_row["session_id"] or "").strip()
    metadata = {
        "session_id": session_id,
        "rules": {
            "template_only": True,
            "platform": "qq",
            "active_window": f"{PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_user_message_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
        },
        "target_last_seen_at": target_row["last_seen_at"],
        "auto_created_at": _now_iso(),
        "source": "auto_scheduler",
    }
    candidate = add_proactive_candidate(
        platform="qq",
        target_hash=target_hash,
        target_label=str(target_row["target_label"] or _mask_hash(target_hash)),
        message=random.choice(SAFE_TEMPLATES),
        reason="auto v3 fixed template",
        status="pending",
        source="auto",
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )
    record_proactive_event(
        event_type="candidate_generated",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="candidate_generated",
        success=True,
        skipped=False,
        metadata={"source": "auto_scheduler"},
    )
    return candidate


def _generated_pending_result(candidate: dict, reason: str | None = None) -> dict[str, Any]:
    result = {
        "success": True,
        "skipped": False,
        "action": "generated_pending",
        "generated_pending": True,
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }
    if reason:
        result["reason"] = reason
    return result


def _record_auto_send_error(candidate_id: int, action: str, error: str) -> None:
    _update_candidate_metadata(
        candidate_id,
        {
            "auto_send_error": (error or "auto send failed")[:160],
            "auto_send_failed_at": _now_iso(),
            "auto_send_action": action,
        },
    )


def _candidate_can_auto_send(candidate: dict, target_row: dict[str, Any]) -> tuple[bool, str | None]:
    if candidate.get("platform") != "qq":
        return False, "auto send only supports qq"
    if candidate.get("status") != "pending":
        return False, "candidate is not pending"
    if int(target_row.get("is_allowed") or 0) != 1:
        return False, "target is not allowed"
    if PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET and not is_allowed_qq_target(str(candidate.get("target_hash") or "")):
        return False, "target is not allowed"
    auto_sent_today = _today_auto_sent_count()
    if auto_sent_today >= PROACTIVE_AUTO_SEND_MAX_PER_DAY:
        return False, f"auto send max per day reached: {PROACTIVE_AUTO_SEND_MAX_PER_DAY}"
    return True, None


def _auto_send_dry_run(candidate: dict) -> dict[str, Any]:
    try:
        send_qq_candidate(candidate_id=candidate["id"], dry_run=True, event_source="auto")
    except HTTPException as exc:
        _record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", str(exc.detail))
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
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
        _record_auto_send_error(candidate["id"], "auto_send_dry_run_failed", type(exc).__name__)
        record_proactive_event(
            event_type="auto_send_dry_run",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_dry_run_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_dry_run_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    _update_candidate_metadata(
        candidate["id"],
        {
            "auto_send_dry_run": True,
            "auto_send_dry_run_at": _now_iso(),
            "auto_send_action": "auto_send_dry_run_ok",
        },
    )
    record_proactive_event(
        event_type="auto_send_dry_run",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_send_dry_run_ok",
        success=True,
        skipped=False,
    )
    return {
        "success": True,
        "skipped": False,
        "action": "auto_send_dry_run_ok",
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }


def _auto_send_real(candidate: dict, target_row: dict[str, Any]) -> dict[str, Any]:
    can_send, blocked_reason = _candidate_can_auto_send(candidate, target_row)
    if not can_send:
        _update_candidate_metadata(
            candidate["id"],
            {
                "auto_send_blocked": True,
                "auto_send_blocked_at": _now_iso(),
                "auto_send_blocked_reason": blocked_reason,
            },
        )
        return _generated_pending_result(candidate, blocked_reason)

    try:
        send_qq_candidate(candidate_id=candidate["id"], dry_run=False, event_source="auto")
    except HTTPException as exc:
        _record_auto_send_error(candidate["id"], "auto_send_failed", str(exc.detail))
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
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
        _record_auto_send_error(candidate["id"], "auto_send_failed", type(exc).__name__)
        update_proactive_candidate_status(candidate["id"], "failed")
        record_proactive_event(
            event_type="auto_send_failed",
            platform="qq",
            target_label=candidate.get("target_label"),
            candidate_id=candidate["id"],
            action="auto_send_failed",
            success=False,
            skipped=False,
            reason=type(exc).__name__,
        )
        return {
            "success": False,
            "skipped": False,
            "action": "auto_send_failed",
            "candidate_id": candidate["id"],
            "error": type(exc).__name__,
        }

    _update_candidate_metadata(
        candidate["id"],
        {
            "auto_sent": True,
            "auto_sent_at": _now_iso(),
            "auto_send_action": "auto_sent",
        },
    )
    record_proactive_event(
        event_type="auto_sent",
        platform="qq",
        target_label=candidate.get("target_label"),
        candidate_id=candidate["id"],
        action="auto_sent",
        success=True,
        skipped=False,
    )
    return {
        "success": True,
        "skipped": False,
        "sent": True,
        "action": "auto_sent",
        "candidate_id": candidate["id"],
        "target_label": candidate.get("target_label"),
    }


def _check_and_send_once() -> dict[str, Any]:
    now = datetime.now()

    if not _within_active_window(now):
        return _skip(f"outside active window: {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}")

    probability = max(0.0, min(1.0, PROACTIVE_RANDOM_PROBABILITY))
    if random.random() >= probability:
        return _skip("random probability missed")

    sent_count = _today_sent_count()
    if sent_count >= PROACTIVE_DAILY_LIMIT:
        return _skip(f"daily sent limit reached: {PROACTIVE_DAILY_LIMIT}")

    last_sent = _parse_sqlite_datetime(_last_sent_at())
    if last_sent is not None and now - last_sent < timedelta(minutes=PROACTIVE_MIN_INTERVAL_MINUTES):
        return _skip(f"last sent is within {PROACTIVE_MIN_INTERVAL_MINUTES} minutes")

    if _has_recent_user_message():
        return _skip(f"qq user message seen within {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes")

    if _has_pending_qq_candidate():
        return _skip("pending qq candidate exists")

    target_row = _latest_qq_target()
    if target_row is None:
        return _skip("no allowed qq target found in proactive_targets")

    target_hash = str(target_row["target_hash"] or "")
    if not is_allowed_qq_target(target_hash):
        return _skip("latest qq target is not whitelisted")

    candidate = _create_auto_candidate(target_row)
    if not PROACTIVE_AUTO_SEND:
        return _generated_pending_result(candidate)

    if PROACTIVE_AUTO_SEND_DRY_RUN:
        return _auto_send_dry_run(candidate)

    return _auto_send_real(candidate, target_row)


async def run_proactive_check_once() -> dict[str, Any]:
    global _last_check_at, _last_result
    _last_check_at = _now_iso()
    _last_result = await asyncio.to_thread(_check_and_send_once)
    record_proactive_event(
        event_type="scheduler_check",
        platform="qq",
        target_label=_last_result.get("target_label"),
        candidate_id=_last_result.get("candidate_id"),
        action=_last_result.get("action") or ("skipped" if _last_result.get("skipped") else "checked"),
        success=_last_result.get("success"),
        skipped=_last_result.get("skipped"),
        reason=_last_result.get("reason") or _last_result.get("error"),
        metadata={
            "last_check_at": _last_check_at,
            "sent": _last_result.get("sent"),
            "generated_pending": _last_result.get("generated_pending"),
        },
    )
    return _last_result


async def _scheduler_loop() -> None:
    while True:
        try:
            result = await run_proactive_check_once()
            print("proactive scheduler check:", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("proactive scheduler failed:", type(exc).__name__)
        await asyncio.sleep(PROACTIVE_CHECK_INTERVAL_SECONDS)


def start_proactive_scheduler() -> asyncio.Task | None:
    global _scheduler_task
    if not PROACTIVE_ENABLED:
        print("proactive scheduler disabled")
        return None
    if _scheduler_task is not None and not _scheduler_task.done():
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    print("proactive scheduler started")
    return _scheduler_task


async def stop_proactive_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = None
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None


def get_proactive_scheduler_status() -> dict[str, Any]:
    rule_evaluation = evaluate_proactive_rules(include_enabled=True)
    auto_sent_today = _today_auto_sent_count()
    return {
        "success": True,
        "enabled": PROACTIVE_ENABLED,
        "task_running": _scheduler_task is not None and not _scheduler_task.done(),
        "daily_limit": PROACTIVE_DAILY_LIMIT,
        "auto_send_enabled": PROACTIVE_AUTO_SEND,
        "auto_send_dry_run": PROACTIVE_AUTO_SEND_DRY_RUN,
        "auto_send_require_allowed_target": PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
        "auto_send_max_per_day": PROACTIVE_AUTO_SEND_MAX_PER_DAY,
        "auto_sent_today": auto_sent_today,
        "config": {
            "check_interval_seconds": PROACTIVE_CHECK_INTERVAL_SECONDS,
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_chat_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "active_start": PROACTIVE_ACTIVE_START,
            "active_end": PROACTIVE_ACTIVE_END,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
            "auto_send": PROACTIVE_AUTO_SEND,
            "auto_send_dry_run": PROACTIVE_AUTO_SEND_DRY_RUN,
            "auto_send_require_allowed_target": PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
            "auto_send_max_per_day": PROACTIVE_AUTO_SEND_MAX_PER_DAY,
        },
        "qq_allowed_target_count": len(PROACTIVE_QQ_ALLOWED_TARGET_HASHES),
        "today_sent_count": _today_sent_count(),
        "last_sent_at": _last_sent_at(),
        "last_check_at": _last_check_at,
        "last_result": _with_explained_reason(_last_result),
        "next_rules_summary": _next_rules_summary(),
        "can_send_now": {
            "can_send": rule_evaluation["can_send"],
            "reason": rule_evaluation["reason"],
        },
    }


def check_proactive_now() -> dict[str, Any]:
    evaluation = evaluate_proactive_rules(include_enabled=True)
    record_proactive_event(
        event_type="scheduler_check",
        platform="qq",
        action="check_now",
        success=True,
        skipped=not evaluation["can_send"],
        reason=evaluation["reason"],
        metadata={"manual_check": True},
    )
    return {
        "success": True,
        "can_send": evaluation["can_send"],
        "reason": evaluation["reason"],
        "checks": evaluation["checks"],
    }
