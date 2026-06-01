import asyncio
import json as _json
import logging
import random
from datetime import datetime, timedelta
from typing import Any

from app.config import (
    BRAIN_INTENT_CONSUMER_ENABLED,
    BRAIN_WHITELIST_USERS,
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_AUTO_SEND,
    PROACTIVE_AUTO_SEND_DRY_RUN,
    PROACTIVE_AUTO_SEND_MAX_PER_DAY,
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
    PROACTIVE_CHECK_INTERVAL_SECONDS,
    PROACTIVE_DAILY_LIMIT,
    PROACTIVE_ENABLED,
    PROACTIVE_FAILURE_PAUSE_THRESHOLD,
    PROACTIVE_HARD_COOLDOWN_MINUTES,
    PROACTIVE_MIN_INTERVAL_MINUTES,
    PROACTIVE_MODE,
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES,
    PROACTIVE_RANDOM_PROBABILITY,
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
)
from app.services.proactive import state
from app.services.proactive.candidate_service import create_auto_candidate
from app.services.proactive.result_helpers import (
    generated_pending_result,
    normalize_manual_run_result,
    now_iso,
    observed_result,
    parse_sqlite_datetime,
    rule,
    skip_result,
    with_explained_reason,
)
from app.services.proactive.rules import (
    consecutive_auto_failures,
    evaluate_proactive_rules,
    explain_proactive_reason,
    failure_pause_active,
    hard_cooldown_active,
    hard_cooldown_last_event,
    has_pending_platform_candidate,
    has_recent_user_message,
    last_sent_at,
    latest_auto_target,
    latest_targets_summary,
    next_rules_summary,
    proactive_mode_description,
    proactive_mode_effective_action,
    proactive_mode_label,
    today_auto_sent_count,
    today_sent_count,
    within_active_window,
)
from app.services.proactive.send_executor import auto_send_dry_run, auto_send_real, send_brain_intent
from app.services.proactive_service import _mask_hash, is_allowed_qq_target, record_proactive_event
from app.storage.db import execute_write, fetch_one, get_latest_proactive_target, get_proactive_target_by_session
from app.utils.logging_utils import log_event, new_trace_id


def proactive_capability_boundary() -> dict[str, Any]:
    return {
        "manual_candidate_platforms": ["qq", "wx"],
        "manual_send_platforms": ["qq", "wx"],
        "visible_platforms": ["qq", "wx"],
        "auto_scheduler_scope": "qq_first",
        "auto_scheduler_scope_label": "QQ-first",
        "auto_scheduler_summary": (
            "自动调度当前按 QQ-first 收口。QQ 是已验收主路径；WX 只保留最小目标可见性、候选可见性和手动发送链路，"
            "不视为 auto 平台化已完成。"
        ),
    }


def check_and_send_once(
    *,
    ignore_random: bool = False,
    ignore_recent_chat: bool = False,
    ignore_active_window: bool = False,
    force: bool = False,
    dry_run_only: bool = False,
    event_source: str = "auto",
    trace_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now()
    checks: list[dict[str, Any]] = []
    selected_platform: str | None = None

    log_event(
        "proactive",
        "proactive_check",
        trace_id=trace_id,
        action=event_source,
        dry_run=dry_run_only or PROACTIVE_MODE == "dry_run",
        auto_send=PROACTIVE_MODE == "auto",
        proactive_mode=PROACTIVE_MODE,
    )

    checks.append(
        rule(
            "proactive_mode",
            PROACTIVE_MODE != "off",
            f"当前模式：{proactive_mode_label()}；{proactive_mode_description()}",
        )
    )
    if PROACTIVE_MODE == "off":
        return skip_result("proactive mode off", checks, trace_id=trace_id, platform=selected_platform)

    checks.append(
        rule(
            "enabled",
            None,
            "旧 PROACTIVE_ENABLED=true" if PROACTIVE_ENABLED else "旧 PROACTIVE_ENABLED=false；实际以 PROACTIVE_MODE 为准",
        )
    )

    cooldown_event = hard_cooldown_last_event()
    hard_cooldown_ok = cooldown_event is None
    checks.append(
        rule(
            "hard_cooldown",
            hard_cooldown_ok,
            f"硬冷却未触发，窗口 {PROACTIVE_HARD_COOLDOWN_MINUTES} 分钟"
            if hard_cooldown_ok
            else f"硬冷却中，最近动作 {cooldown_event.get('action') or cooldown_event.get('event_type')} / {cooldown_event.get('created_at')}",
        )
    )
    if not hard_cooldown_ok and PROACTIVE_MODE != "observe":
        return skip_result("hard cooldown active", checks, trace_id=trace_id)

    consecutive_failures = consecutive_auto_failures()
    failure_pause_ok = (
        PROACTIVE_FAILURE_PAUSE_THRESHOLD <= 0
        or consecutive_failures < PROACTIVE_FAILURE_PAUSE_THRESHOLD
    )
    checks.append(
        rule(
            "failure_pause",
            failure_pause_ok,
            f"连续自动发送失败 {consecutive_failures}/{PROACTIVE_FAILURE_PAUSE_THRESHOLD}",
        )
    )
    if not failure_pause_ok and PROACTIVE_MODE != "observe":
        return skip_result("auto send failure pause", checks, trace_id=trace_id)

    active_ok = within_active_window(now)
    checks.append(
        rule(
            "active_window",
            None if ignore_active_window else active_ok,
            "本次手动触发忽略时间窗"
            if ignore_active_window
            else f"当前时间 {'在' if active_ok else '不在'}允许主动消息时间段 {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
        )
    )
    if not ignore_active_window and not active_ok:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result(
            f"outside active window: {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
            checks,
            trace_id=trace_id,
            platform=selected_platform,
        )

    probability = max(0.0, min(1.0, PROACTIVE_RANDOM_PROBABILITY))
    if ignore_random:
        checks.append(rule("random_probability", None, "本次手动触发忽略随机概率"))
    else:
        random_hit = random.random() < probability
        checks.append(
            rule(
                "random_probability",
                random_hit,
                f"随机概率 {probability}，本轮{'命中' if random_hit else '未命中'}",
            )
        )
        if not random_hit:
            if PROACTIVE_MODE == "observe":
                return observed_result(checks, trace_id=trace_id)
            return skip_result("random probability missed", checks, trace_id=trace_id, platform=selected_platform)

    sent_count = today_sent_count()
    daily_ok = sent_count < PROACTIVE_DAILY_LIMIT
    checks.append(
        rule(
            "daily_limit",
            daily_ok,
            f"今天已自动发送 {sent_count}/{PROACTIVE_DAILY_LIMIT} 条",
        )
    )
    if not daily_ok:
            if PROACTIVE_MODE == "observe":
                return observed_result(checks, trace_id=trace_id)
            return skip_result(f"daily sent limit reached: {PROACTIVE_DAILY_LIMIT}", checks, trace_id=trace_id, platform=selected_platform)

    last_sent = parse_sqlite_datetime(last_sent_at())
    min_interval_ok = last_sent is None or now - last_sent >= timedelta(minutes=PROACTIVE_MIN_INTERVAL_MINUTES)
    if last_sent is None:
        min_interval_detail = "还没有自动主动消息发送记录"
    else:
        elapsed_minutes = int((now - last_sent).total_seconds() // 60)
        min_interval_detail = f"距离上次自动主动消息约 {elapsed_minutes} 分钟，要求至少 {PROACTIVE_MIN_INTERVAL_MINUTES} 分钟"
    checks.append(rule("min_interval", min_interval_ok, min_interval_detail))
    if not min_interval_ok:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result(f"last sent is within {PROACTIVE_MIN_INTERVAL_MINUTES} minutes", checks, trace_id=trace_id, platform=selected_platform)

    target_row = latest_auto_target()
    selected_platform = str(target_row.get("platform") or "").strip().lower() if target_row else None
    target_hash = str(target_row.get("target_hash") or "") if target_row else ""
    checks.append(
        {
            **rule(
                "auto_target",
                target_row is not None,
            (
                    f"最近自动判断目标平台 {selected_platform} / {_mask_hash(target_hash)}"
                    if target_row and selected_platform
                    else "没有找到自动主动目标"
                ),
            ),
            "platform": selected_platform,
        }
    )
    if target_row is None:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result("no auto target found in proactive_targets", checks, trace_id=trace_id, platform=selected_platform)

    recent_chat = has_recent_user_message(selected_platform)
    checks.append(
        rule(
            "recent_chat",
            None if ignore_recent_chat else not recent_chat,
            "本次手动触发忽略最近聊天规则"
            if ignore_recent_chat
            else f"最近 {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} 分钟{'有' if recent_chat else '没有'} {selected_platform} 用户消息",
        )
    )
    if not ignore_recent_chat and recent_chat:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result(
            f"{selected_platform} user message seen within {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} minutes",
            checks,
            trace_id=trace_id,
            platform=selected_platform,
        )

    pending_candidate = has_pending_platform_candidate(selected_platform)
    checks.append(
        rule(
            "pending_candidate",
            None if force else not pending_candidate,
            "本次强制生成，已有 pending 不阻止新候选"
            if force
            else f"已有待处理 {selected_platform} 候选" if pending_candidate else f"没有待处理 {selected_platform} 候选",
        )
    )
    if not force and pending_candidate:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result(f"pending {selected_platform} candidate exists", checks, trace_id=trace_id, platform=selected_platform)

    whitelist_ok = selected_platform == "wx" or (bool(target_hash) and is_allowed_qq_target(target_hash))
    checks.append(
        rule(
            "platform_permission",
            whitelist_ok,
            (
                "最近命中的是 WX 目标；当前只保留最小链路观察与手动发送支持，不视为 auto 平台化已完成"
                if selected_platform == "wx"
                else "最近 QQ 目标在白名单内" if whitelist_ok else "最近 QQ 目标不在白名单内"
            ),
        )
    )
    if not whitelist_ok:
        if PROACTIVE_MODE == "observe":
            return observed_result(checks, trace_id=trace_id)
        return skip_result(f"latest {selected_platform} target is not allowed", checks, trace_id=trace_id, platform=selected_platform)

    if PROACTIVE_MODE == "observe":
        return observed_result(checks, trace_id=trace_id)

    candidate = create_auto_candidate(target_row, trace_id=trace_id)
    if PROACTIVE_MODE == "candidate":
        result = generated_pending_result(candidate)
        result["checks"] = checks
        return result

    if PROACTIVE_MODE == "dry_run" or dry_run_only:
        result = auto_send_dry_run(candidate, event_source=event_source, trace_id=trace_id)
        result["checks"] = checks
        return result

    result = auto_send_real(candidate, target_row, trace_id=trace_id)
    result["checks"] = checks
    return result


async def run_proactive_check_once(trace_id: str | None = None) -> dict[str, Any]:
    trace_id = trace_id or new_trace_id()
    state.last_check_at = now_iso()
    state.last_result = await asyncio.to_thread(check_and_send_once, trace_id=trace_id)
    record_proactive_event(
        event_type="scheduler_check",
        platform=state.last_result.get("platform"),
        target_label=state.last_result.get("target_label"),
        candidate_id=state.last_result.get("candidate_id"),
        action=state.last_result.get("action") or ("skipped" if state.last_result.get("skipped") else "checked"),
        success=state.last_result.get("success"),
        skipped=state.last_result.get("skipped"),
        reason=state.last_result.get("reason") or state.last_result.get("error"),
        metadata={
            "last_check_at": state.last_check_at,
            "sent": state.last_result.get("sent"),
            "generated_pending": state.last_result.get("generated_pending"),
            "proactive_mode": PROACTIVE_MODE,
        },
    )
    log_event(
        "proactive",
        "proactive_check",
        trace_id=trace_id,
        target_label=state.last_result.get("target_label"),
        candidate_id=state.last_result.get("candidate_id"),
        action=state.last_result.get("action") or ("skipped" if state.last_result.get("skipped") else "checked"),
        success=state.last_result.get("success"),
        skipped=state.last_result.get("skipped"),
        reason=state.last_result.get("reason") or state.last_result.get("error"),
        auto_send=PROACTIVE_MODE == "auto",
        dry_run=PROACTIVE_MODE == "dry_run",
        proactive_mode=PROACTIVE_MODE,
    )
    return state.last_result


def run_proactive_once_manual(
    *,
    ignore_random: bool = True,
    ignore_recent_chat: bool = False,
    ignore_active_window: bool = False,
    force: bool = False,
    dry_run_only: bool = True,
    trace_id: str | None = None,
) -> dict[str, Any]:
    trace_id = trace_id or new_trace_id()
    state.last_check_at = now_iso()
    try:
        raw_result = check_and_send_once(
            ignore_random=ignore_random,
            ignore_recent_chat=ignore_recent_chat,
            ignore_active_window=ignore_active_window,
            force=force,
            dry_run_only=dry_run_only,
            event_source="manual_scheduler_run",
            trace_id=trace_id,
        )
    except Exception as exc:
        raw_result = {
            "success": False,
            "skipped": False,
            "action": "failed",
            "error": getattr(exc, "detail", None) or type(exc).__name__,
            "checks": [],
        }

    response = normalize_manual_run_result(
        raw_result,
        dry_run_only=dry_run_only,
        explain_reason=explain_proactive_reason,
    )
    response.update(proactive_capability_boundary())
    state.last_result = response
    record_proactive_event(
        event_type="manual_scheduler_run",
        platform=raw_result.get("platform"),
        target_label=raw_result.get("target_label"),
        candidate_id=response.get("candidate_id"),
        action=response.get("action"),
        success=response.get("success"),
        skipped=response.get("action") == "skipped"
        or (response.get("action") == "observed" and response.get("would_pass") is False),
        reason=response.get("reason"),
        metadata={
            "last_check_at": state.last_check_at,
            "ignore_random": ignore_random,
            "ignore_recent_chat": ignore_recent_chat,
            "ignore_active_window": ignore_active_window,
            "force": force,
            "dry_run_only": dry_run_only,
            "raw_action": raw_result.get("action"),
            "proactive_mode": PROACTIVE_MODE,
        },
    )
    log_event(
        "proactive",
        "proactive_run_once",
        trace_id=trace_id,
        target_label=raw_result.get("target_label"),
        candidate_id=response.get("candidate_id"),
        action=response.get("action"),
        success=response.get("success"),
        skipped=response.get("action") == "skipped"
        or (response.get("action") == "observed" and response.get("would_pass") is False),
        reason=response.get("reason"),
        dry_run=dry_run_only,
        auto_send=PROACTIVE_MODE == "auto",
        proactive_mode=PROACTIVE_MODE,
    )
    return response


def get_proactive_scheduler_status() -> dict[str, Any]:
    rule_evaluation = evaluate_proactive_rules(include_enabled=True)
    auto_sent_today = today_auto_sent_count()
    hard_cooldown = hard_cooldown_active()
    consecutive_failures = consecutive_auto_failures()
    failure_pause = failure_pause_active()
    boundary = proactive_capability_boundary()
    return {
        "success": True,
        "enabled": PROACTIVE_ENABLED,
        "proactive_mode": PROACTIVE_MODE,
        "mode_label": proactive_mode_label(),
        "mode_description": proactive_mode_description(),
        "mode_effective_action": proactive_mode_effective_action(),
        "task_running": state.scheduler_task is not None and not state.scheduler_task.done(),
        "daily_limit": PROACTIVE_DAILY_LIMIT,
        "auto_send_enabled": PROACTIVE_AUTO_SEND,
        "auto_send_dry_run": PROACTIVE_AUTO_SEND_DRY_RUN,
        "auto_send_require_allowed_target": PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
        "auto_send_max_per_day": PROACTIVE_AUTO_SEND_MAX_PER_DAY,
        "auto_sent_today": auto_sent_today,
        "supported_platforms": boundary["visible_platforms"],
        "manual_candidate_platforms": boundary["manual_candidate_platforms"],
        "manual_send_platforms": boundary["manual_send_platforms"],
        "visible_platforms": boundary["visible_platforms"],
        "auto_scheduler_scope": boundary["auto_scheduler_scope"],
        "auto_scheduler_scope_label": boundary["auto_scheduler_scope_label"],
        "auto_scheduler_summary": boundary["auto_scheduler_summary"],
        "hard_cooldown_minutes": PROACTIVE_HARD_COOLDOWN_MINUTES,
        "failure_pause_threshold": PROACTIVE_FAILURE_PAUSE_THRESHOLD,
        "hard_cooldown_active": hard_cooldown,
        "consecutive_auto_failures": consecutive_failures,
        "failure_pause_active": failure_pause,
        "config": {
            "proactive_mode": PROACTIVE_MODE,
            "check_interval_seconds": PROACTIVE_CHECK_INTERVAL_SECONDS,
            "daily_limit": PROACTIVE_DAILY_LIMIT,
            "min_interval_minutes": PROACTIVE_MIN_INTERVAL_MINUTES,
            "recent_chat_skip_minutes": PROACTIVE_RECENT_CHAT_SKIP_MINUTES,
            "hard_cooldown_minutes": PROACTIVE_HARD_COOLDOWN_MINUTES,
            "failure_pause_threshold": PROACTIVE_FAILURE_PAUSE_THRESHOLD,
            "active_start": PROACTIVE_ACTIVE_START,
            "active_end": PROACTIVE_ACTIVE_END,
            "random_probability": PROACTIVE_RANDOM_PROBABILITY,
            "auto_send": PROACTIVE_AUTO_SEND,
            "auto_send_dry_run": PROACTIVE_AUTO_SEND_DRY_RUN,
            "auto_send_require_allowed_target": PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET,
            "auto_send_max_per_day": PROACTIVE_AUTO_SEND_MAX_PER_DAY,
        },
        "qq_allowed_target_count": len(PROACTIVE_QQ_ALLOWED_TARGET_HASHES),
        "latest_targets": latest_targets_summary(),
        "today_sent_count": today_sent_count(),
        "last_sent_at": last_sent_at(),
        "last_check_at": state.last_check_at,
        "last_result": with_explained_reason(state.last_result, explain_proactive_reason),
        "next_rules_summary": next_rules_summary(),
        "can_send_now": {
            "can_send": rule_evaluation["can_send"],
            "reason": rule_evaluation["reason"],
            "platform": rule_evaluation.get("platform"),
            "target_summary": rule_evaluation.get("target_summary"),
        },
    }


def check_proactive_now(trace_id: str | None = None) -> dict[str, Any]:
    trace_id = trace_id or new_trace_id()
    evaluation = evaluate_proactive_rules(include_enabled=True)
    record_proactive_event(
        event_type="scheduler_check",
        platform=evaluation.get("platform"),
        action="check_now",
        success=True,
        skipped=not evaluation["can_send"],
        reason=evaluation["reason"],
        metadata={"manual_check": True, "proactive_mode": PROACTIVE_MODE},
    )
    log_event(
        "proactive",
        "proactive_check",
        trace_id=trace_id,
        action="check_now",
        success=True,
        skipped=not evaluation["can_send"],
        reason=evaluation["reason"],
        auto_send=PROACTIVE_MODE == "auto",
        dry_run=PROACTIVE_MODE == "dry_run",
        proactive_mode=PROACTIVE_MODE,
    )
    return {
        "success": True,
        "proactive_mode": PROACTIVE_MODE,
        "can_send": evaluation["can_send"],
        "reason": evaluation["reason"],
        "platform": evaluation.get("platform"),
        "target_summary": evaluation.get("target_summary"),
        "checks": evaluation["checks"],
        **proactive_capability_boundary(),
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 3b: Brain Intent 消费（不改上方现有函数）
# ──────────────────────────────────────────────────────────────────────

_brain_logger = logging.getLogger(__name__)


def consume_brain_intents() -> dict:
    """
    消费 proactive_intent 表中 status='queued' 的意图。
    每次只消费一条（FIFO），经漏斗检查后调用 send_brain_intent()。

    ⚠️ 漏斗检查复用 rules.py 现有函数，逻辑完全不变。
    ⚠️ 不改 check_and_send_once()，两条路径完全独立。
    ⚠️ 白名单为空 = brain send 子系统关闭，intent 保持 queued 积压（设计意图）。

    同步函数，由 async wrapper 通过 asyncio.to_thread 调用。
    """
    trace_id = new_trace_id()

    # ── 总开关检查 ──
    if not BRAIN_INTENT_CONSUMER_ENABLED:
        _brain_logger.debug("[%s] consume_brain_intents: consumer disabled", trace_id)
        return {"action": "consumer_disabled", "sent": False}

    # ── 取第一条 queued 意图 ──
    row = fetch_one(
        "SELECT id, user_id, fragments FROM proactive_intent "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    )
    if not row:
        return {"action": "no_intent", "sent": False}

    intent_id = int(row["id"])
    user_id = str(row["user_id"] or "")
    fragments_json = str(row["fragments"] or "[]")

    # ── 白名单检查（硬性前置，漏斗之前）──
    # 空列表 = brain send 子系统关闭，queued intent 保持积压。
    # 这是设计意图：brain 生成照常运行，发送端按白名单控制开关。
    if not BRAIN_WHITELIST_USERS:
        _brain_logger.debug("[%s] brain intent skipped: whitelist empty (subsystem off)", trace_id)
        return {"action": "whitelist_empty", "sent": False}

    if user_id not in BRAIN_WHITELIST_USERS:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.info("[%s] brain intent dropped: user %s not in whitelist", trace_id, user_id)
        return {"action": "whitelist_skip", "sent": False}

    # ── 漏斗检查（复用 rules.py，只调用不改）──
    if hard_cooldown_active():
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.info("[%s] brain intent dropped: hard_cooldown", trace_id)
        return {"action": "hard_cooldown", "sent": False}

    if failure_pause_active():
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.info("[%s] brain intent dropped: failure_pause", trace_id)
        return {"action": "failure_pause", "sent": False}

    if not within_active_window(datetime.now()):
        # 不发但不丢弃，等进入活跃窗口再发
        _brain_logger.debug("[%s] brain intent deferred: outside active window", trace_id)
        return {"action": "outside_window", "sent": False}

    if today_sent_count() >= PROACTIVE_DAILY_LIMIT:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.info("[%s] brain intent dropped: daily_limit reached", trace_id)
        return {"action": "daily_limit", "sent": False}

    # ── recent chat 检查 ──
    platform = user_id.split(":")[0] if user_id else ""
    if platform and has_recent_user_message(platform):
        # 不发但不丢弃，等用户安静后再发
        _brain_logger.debug(
            "[%s] brain intent deferred: recent %s chat", trace_id, platform,
        )
        return {"action": "recent_chat_defer", "sent": False}

    # ── 解析 fragments 并发送 ──
    try:
        fragments = _json.loads(fragments_json)
    except (ValueError, TypeError) as e:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.error("[%s] brain intent dropped: invalid fragments JSON: %s", trace_id, e)
        return {"action": "invalid_fragments", "sent": False}

    if not isinstance(fragments, list) or not fragments:
        execute_write(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        _brain_logger.error("[%s] brain intent dropped: empty fragments", trace_id)
        return {"action": "empty_fragments", "sent": False}

    result = send_brain_intent(user_id, fragments, trace_id, intent_id)

    # ── 记录 proactive_events ──
    try:
        record_proactive_event(
            event_type="brain_intent_consumed",
            platform=platform or None,
            action="sent" if result["success"] else "failed",
            success=result["success"],
            reason=result.get("error"),
            metadata={
                "intent_id": intent_id,
                "sent_count": result.get("sent_count", 0),
                "total": result.get("total", 0),
            },
        )
    except Exception:
        pass

    return {
        "action": "sent" if result["success"] else "send_failed",
        "sent": result["success"],
        **result,
    }


async def run_consume_brain_intents(trace_id: str | None = None) -> dict:
    """async 入口，供 APScheduler 调用。内部通过 asyncio.to_thread 执行同步函数。"""
    return await asyncio.to_thread(consume_brain_intents)


def preflight_brain_intent() -> dict:
    """
    Phase 3b 只读预检：评估"能不能安全发送"，不触发任何副作用。
    不创建 proactive_candidates，不调用 send_proactive_candidate，
    不更新 proactive_intent.status，不写 debug_events。

    供 GET /debug/consciousness/phase3b/preflight 调用。
    """
    result = {
        "consumer_enabled": BRAIN_INTENT_CONSUMER_ENABLED,
        "whitelist_users": list(BRAIN_WHITELIST_USERS),
        "next_queued_intent": None,
        "whitelist_match": False,
        "target_lookup": None,
        "rules": {},
        "decision": {},
    }

    # ── 读取最新 queued intent ──
    row = fetch_one(
        "SELECT id, user_id, status, fragments, created_at "
        "FROM proactive_intent "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    )
    if not row:
        result["decision"] = {
            "ready_to_send": False,
            "status": "no_intent",
            "reason": "proactive_intent 表中没有 queued 意图",
            "expected_candidates": 0,
        }
        return result

    intent_id = int(row["id"])
    user_id = str(row["user_id"] or "")
    fragments_json = str(row["fragments"] or "[]")
    try:
        fragments = _json.loads(fragments_json)
        fragments_count = len(fragments) if isinstance(fragments, list) else 0
    except (ValueError, TypeError):
        fragments_count = 0

    result["next_queued_intent"] = {
        "id": intent_id,
        "user_id": user_id,
        "status": str(row["status"] or ""),
        "fragments_count": fragments_count,
        "created_at": str(row["created_at"] or ""),
    }

    # ── fragments_preview：前 3 条，每条最多 30 字 ──
    preview_list = []
    if isinstance(fragments, list):
        for frag in fragments[:3]:
            s = str(frag or "")
            preview_list.append(s[:30] + ("…" if len(s) > 30 else ""))
    result["fragments_preview"] = preview_list

    # ── debug 字段：始终写入，方便排查 whitelist_match=false 的字符差异 ──
    result["intent_user_id_raw"] = user_id
    result["whitelist_users_raw"] = list(BRAIN_WHITELIST_USERS)
    result["intent_user_id_repr"] = repr(user_id)
    result["whitelist_users_repr"] = [repr(u) for u in BRAIN_WHITELIST_USERS]
    result["whitelist_match"] = user_id in BRAIN_WHITELIST_USERS
    result["whitelist_contains"] = {
        u: (user_id == u) for u in BRAIN_WHITELIST_USERS
    }

    # ── consumer 开关 ──
    if not BRAIN_INTENT_CONSUMER_ENABLED:
        result["decision"] = {
            "ready_to_send": False,
            "status": "disabled",
            "reason": "BRAIN_INTENT_CONSUMER_ENABLED=false，消费器未启动",
            "expected_candidates": fragments_count,
        }
        return result

    # ── 白名单检查 ──
    if not BRAIN_WHITELIST_USERS:
        result["decision"] = {
            "ready_to_send": False,
            "status": "whitelist_empty",
            "reason": "BRAIN_WHITELIST_USERS 为空，brain send 子系统关闭，intent 保持积压",
            "expected_candidates": fragments_count,
        }
        return result

    if not result["whitelist_match"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "whitelist_skip",
            "reason": f"user_id '{user_id}' 不在白名单中",
            "expected_candidates": fragments_count,
        }
        return result

    # ── Target 查找（只读，精确查）──
    parts = (user_id or "").split(":")
    platform = parts[0] if parts else ""
    session_id = user_id
    target_row = get_proactive_target_by_session(platform, session_id) if platform else None

    if target_row:
        real_uid = str(target_row.get("real_user_id") or "").strip()
        result["target_lookup"] = {
            "platform": platform,
            "session_id": session_id,
            "found": True,
            "real_user_id_masked": _mask_hash(real_uid) if real_uid else None,
        }
    else:
        result["target_lookup"] = {
            "platform": platform,
            "session_id": session_id,
            "found": False,
            "real_user_id_masked": None,
        }
        result["decision"] = {
            "ready_to_send": False,
            "status": "no_target",
            "reason": f"proactive_targets 中无 platform='{platform}' session_id='{session_id}' 对应记录",
            "expected_candidates": fragments_count,
        }
        return result

    # ── 漏斗规则检查（只读）──
    rules = {}
    rules["hard_cooldown_active"] = hard_cooldown_active()
    rules["failure_pause_active"] = failure_pause_active()
    rules["within_active_window"] = within_active_window(datetime.now())
    rules["today_sent_count"] = today_sent_count()
    rules["daily_limit"] = PROACTIVE_DAILY_LIMIT
    rules["has_recent_user_message"] = has_recent_user_message(platform) if platform else False
    result["rules"] = rules

    # ── 决策 ──
    if rules["hard_cooldown_active"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "hard_cooldown",
            "reason": f"硬冷却中，intent 将被 dropped",
            "expected_candidates": fragments_count,
        }
        return result

    if rules["failure_pause_active"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "failure_pause",
            "reason": f"连续失败达阈值，intent 将被 dropped",
            "expected_candidates": fragments_count,
        }
        return result

    if not rules["within_active_window"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "outside_window",
            "reason": f"不在活跃窗口内，intent 保持 queued 等待",
            "expected_candidates": fragments_count,
        }
        return result

    if rules["today_sent_count"] >= rules["daily_limit"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "daily_limit",
            "reason": f"今日已发送 {rules['today_sent_count']}/{rules['daily_limit']}，intent 将被 dropped",
            "expected_candidates": fragments_count,
        }
        return result

    if rules["has_recent_user_message"]:
        result["decision"] = {
            "ready_to_send": False,
            "status": "recent_chat_defer",
            "reason": f"最近有 {platform} 用户消息，intent 保持 queued 等待",
            "expected_candidates": fragments_count,
        }
        return result

    # ── 全部通过 ──
    result["decision"] = {
        "ready_to_send": True,
        "status": "ready",
        "reason": "所有检查通过，consume_brain_intents 下次调度将发送此 intent",
        "expected_candidates": fragments_count,
    }
    return result


def enqueue_test_intent(
    user_id: str | None = None,
    fragments: list[str] | None = None,
) -> dict:
    """
    Debug-only：往 proactive_intent 写入一条 queued 测试意图。
    不发送、不创建 proactive_candidates、不调用 send_proactive_candidate。
    供 POST /debug/consciousness/phase3b/enqueue_test_intent 调用。
    """
    from app.storage.db import get_conn

    # ── 确定 user_id ──
    if not user_id:
        target = get_latest_proactive_target("wx")
        if target:
            user_id = str(target.get("session_id") or "")
        if not user_id:
            return {"success": False, "error": "no wx target found and no user_id provided"}

    # ── 确定 fragments ──
    if not fragments:
        fragments = ["测试一下，别紧张"]
    fragments = [f.strip() for f in fragments if f.strip()]
    if not fragments:
        return {"success": False, "error": "fragments must not be empty"}

    now = datetime.now().isoformat(timespec="seconds")
    fragments_json = _json.dumps(fragments, ensure_ascii=False)

    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO proactive_intent (user_id, fragments, status, created_at) "
            "VALUES (?, ?, 'queued', ?)",
            (user_id, fragments_json, now),
        )
        new_id = int(cursor.lastrowid)

    _brain_logger.info(
        "enqueue_test_intent: id=%d user=%s fragments=%d",
        new_id, user_id, len(fragments),
    )

    return {
        "success": True,
        "intent": {
            "id": new_id,
            "user_id": user_id,
            "fragments": fragments,
            "status": "queued",
            "created_at": now,
        },
    }


def drop_queued_test_intents() -> dict:
    """
    Debug-only：将所有 status='queued' 的 proactive_intent 标记为 'dropped'。
    不发送、不创建 candidate、不调用 send_proactive_candidate。
    用于灰度前清理测试 intent，避免消费旧测试数据。
    """
    affected = execute_write(
        "UPDATE proactive_intent SET status='dropped' WHERE status='queued'",
    )
    _brain_logger.info("drop_queued_test_intents: dropped %d queued intents", affected)
    return {"success": True, "dropped_count": affected}
