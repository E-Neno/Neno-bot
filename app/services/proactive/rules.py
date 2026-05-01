from datetime import datetime, timedelta
from typing import Any

from app.config import (
    PROACTIVE_ACTIVE_END,
    PROACTIVE_ACTIVE_END_TIME,
    PROACTIVE_ACTIVE_START,
    PROACTIVE_ACTIVE_START_TIME,
    PROACTIVE_AUTO_SEND,
    PROACTIVE_AUTO_SEND_DRY_RUN,
    PROACTIVE_AUTO_SEND_MAX_PER_DAY,
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
from app.services.proactive.result_helpers import parse_sqlite_datetime, rule
from app.services.proactive_service import _mask_hash, is_allowed_qq_target
from app.storage.db import fetch_one, get_latest_allowed_proactive_target

PROACTIVE_MODE_LABELS = {
    "off": "关闭",
    "observe": "观察",
    "candidate": "候选",
    "dry_run": "演习 dry_run",
    "auto": "自动真实发送",
}
PROACTIVE_MODE_DESCRIPTIONS = {
    "off": "完全关闭自动主动消息，不生成候选，不发送。",
    "observe": "只观察并记录调度判断，不生成候选，不发送。",
    "candidate": "规则通过后自动生成 pending 候选，不发送。",
    "dry_run": "规则通过后生成候选并执行 dry_run，不真实发送，不写 messages。",
    "auto": "规则通过后允许自动真实发送；当前仅支持 QQ，成功后才写 messages。",
}
PROACTIVE_MODE_EFFECTIVE_ACTIONS = {
    "off": "skip",
    "observe": "observe_only",
    "candidate": "generate_pending",
    "dry_run": "generate_and_dry_run",
    "auto": "generate_and_send_qq",
}


def within_active_window(now: datetime) -> bool:
    current = now.time()
    if PROACTIVE_ACTIVE_START_TIME <= PROACTIVE_ACTIVE_END_TIME:
        return PROACTIVE_ACTIVE_START_TIME <= current <= PROACTIVE_ACTIVE_END_TIME
    return current >= PROACTIVE_ACTIVE_START_TIME or current <= PROACTIVE_ACTIVE_END_TIME


def today_sent_count() -> int:
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


def today_auto_sent_count() -> int:
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


def last_sent_at() -> str | None:
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


def hard_cooldown_last_event() -> dict[str, Any] | None:
    if PROACTIVE_HARD_COOLDOWN_MINUTES <= 0:
        return None
    row = fetch_one(
        f"""
        SELECT id, created_at, event_type, action
        FROM proactive_events
        WHERE created_at >= datetime('now', '-{PROACTIVE_HARD_COOLDOWN_MINUTES} minutes')
          AND (
            event_type IN ('candidate_generated', 'auto_sent', 'manual_sent', 'auto_send_dry_run')
            OR action IN ('candidate_generated', 'auto_sent', 'manual_sent', 'auto_send_dry_run_ok')
          )
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None


def hard_cooldown_active() -> bool:
    return hard_cooldown_last_event() is not None


def consecutive_auto_failures() -> int:
    recent = fetch_one(
        """
        SELECT id
        FROM proactive_events
        WHERE action IN ('auto_sent', 'auto_send_dry_run_ok')
        ORDER BY id DESC
        LIMIT 1
        """
    )
    last_success_id = int(recent["id"] or 0) if recent else 0
    count_row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM proactive_events
        WHERE action IN ('auto_send_failed', 'auto_send_dry_run_failed')
          AND success = 0
          AND id > ?
        """,
        (last_success_id,),
    )
    return int(count_row["count"] or 0) if count_row else 0


def failure_pause_active() -> bool:
    return PROACTIVE_FAILURE_PAUSE_THRESHOLD > 0 and consecutive_auto_failures() >= PROACTIVE_FAILURE_PAUSE_THRESHOLD


def has_recent_user_message() -> bool:
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


def has_pending_qq_candidate() -> bool:
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


def latest_qq_target() -> dict[str, Any] | None:
    return get_latest_allowed_proactive_target("qq")


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
    if "proactive mode off" in lower:
        return "主动消息模式为关闭，不会自动生成或发送"
    if "hard cooldown active" in lower:
        return "硬冷却中，本轮主动调度跳过"
    if "auto send failure pause" in lower:
        return "连续自动发送失败达到阈值，自动调度暂停"
    if "not whitelisted" in lower:
        return "最新 QQ 目标不在白名单，暂不发送"
    if "no allowed qq target" in lower or "no qq target" in lower:
        return "没有可用 QQ 主动目标，请先给机器人发一条 QQ 消息，并在主动目标中允许该目标。"
    if "disabled" in lower:
        return "自动主动消息未开启"
    return text


def proactive_mode_label(mode: str | None = None) -> str:
    return PROACTIVE_MODE_LABELS.get(mode or PROACTIVE_MODE, mode or PROACTIVE_MODE or "off")


def proactive_mode_description(mode: str | None = None) -> str:
    return PROACTIVE_MODE_DESCRIPTIONS.get(mode or PROACTIVE_MODE, "未知主动消息运行模式。")


def proactive_mode_effective_action(mode: str | None = None) -> str:
    return PROACTIVE_MODE_EFFECTIVE_ACTIONS.get(mode or PROACTIVE_MODE, "unknown")


def next_rules_summary() -> list[str]:
    return [
        f"当前模式：{proactive_mode_label()}",
        proactive_mode_description(),
        "旧 enabled 配置为 true" if PROACTIVE_ENABLED else "旧 enabled 配置为 false",
        "当前只支持 QQ",
        f"每天最多 {PROACTIVE_DAILY_LIMIT} 条",
        f"两次主动消息至少间隔 {PROACTIVE_MIN_INTERVAL_MINUTES} 分钟",
        f"硬冷却 {PROACTIVE_HARD_COOLDOWN_MINUTES} 分钟",
        f"连续自动发送失败 {PROACTIVE_FAILURE_PAUSE_THRESHOLD} 次后暂停",
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

    checks.append(
        rule(
            "proactive_mode",
            PROACTIVE_MODE != "off",
            f"当前模式：{proactive_mode_label()}；{proactive_mode_description()}",
        )
    )

    if include_enabled:
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

    active_ok = within_active_window(now)
    checks.append(
        rule(
            "active_window",
            active_ok,
            f"当前时间 {'在' if active_ok else '不在'}允许主动消息时间段 {PROACTIVE_ACTIVE_START}-{PROACTIVE_ACTIVE_END}",
        )
    )

    sent_count = today_sent_count()
    daily_ok = sent_count < PROACTIVE_DAILY_LIMIT
    checks.append(
        rule(
            "daily_limit",
            daily_ok,
            f"今天已自动发送 {sent_count}/{PROACTIVE_DAILY_LIMIT} 条",
        )
    )

    last_sent = parse_sqlite_datetime(last_sent_at())
    min_interval_ok = last_sent is None or now - last_sent >= timedelta(minutes=PROACTIVE_MIN_INTERVAL_MINUTES)
    if last_sent is None:
        min_interval_detail = "还没有自动主动消息发送记录"
    else:
        elapsed_minutes = int((now - last_sent).total_seconds() // 60)
        min_interval_detail = f"距离上次自动主动消息约 {elapsed_minutes} 分钟，要求至少 {PROACTIVE_MIN_INTERVAL_MINUTES} 分钟"
    checks.append(rule("min_interval", min_interval_ok, min_interval_detail))

    recent_chat = has_recent_user_message()
    checks.append(
        rule(
            "recent_chat",
            not recent_chat,
            f"最近 {PROACTIVE_RECENT_CHAT_SKIP_MINUTES} 分钟{'有' if recent_chat else '没有'} QQ 用户消息",
        )
    )

    pending_candidate = has_pending_qq_candidate()
    checks.append(
        rule(
            "pending_candidate",
            not pending_candidate,
            "已有待处理 QQ 候选" if pending_candidate else "没有待处理 QQ 候选",
        )
    )

    target_row = latest_qq_target()
    target_hash = str(target_row["target_hash"] or "") if target_row else ""
    checks.append(
        rule(
            "qq_target",
            target_row is not None,
            f"最近 QQ 目标 {_mask_hash(target_hash)}" if target_row else "没有找到 QQ 目标",
        )
    )

    whitelist_ok = bool(target_hash) and is_allowed_qq_target(target_hash)
    checks.append(
        rule(
            "qq_whitelist",
            whitelist_ok,
            "最近 QQ 目标在白名单内" if whitelist_ok else "最近 QQ 目标不在白名单内",
        )
    )

    target_allowed = bool(target_row and int(target_row.get("is_allowed") or 0) == 1)
    checks.append(
        rule(
            "allowed_target",
            target_allowed,
            "自动目标已 allowed" if target_allowed else "自动目标未 allowed",
        )
    )

    checks.append(
        rule(
            "auto_send_enabled",
            None,
            "自动真实发送已开启" if PROACTIVE_AUTO_SEND else "自动真实发送关闭：命中后只生成 pending candidate",
        )
    )
    checks.append(
        rule(
            "auto_send_dry_run",
            None,
            "自动发送 dry_run 开启：只测试发送链路" if PROACTIVE_AUTO_SEND_DRY_RUN else "自动发送 dry_run 关闭",
        )
    )
    auto_sent_today = today_auto_sent_count()
    auto_send_limit_ok = auto_sent_today < PROACTIVE_AUTO_SEND_MAX_PER_DAY
    checks.append(
        rule(
            "auto_send_max_per_day",
            auto_send_limit_ok if PROACTIVE_MODE == "auto" else None,
            f"今天自动真实发送 {auto_sent_today}/{PROACTIVE_AUTO_SEND_MAX_PER_DAY} 条",
        )
    )

    checks.append(rule("random_probability", None, "check-now 不掷随机数"))

    first_failed = next((check for check in checks if check["ok"] is False), None)
    can_send = first_failed is None
    reason = "当前规则允许发送；正式调度仍会再判断随机概率" if can_send else str(first_failed["detail"])

    return {
        "can_send": can_send,
        "reason": reason,
        "checks": checks,
    }
