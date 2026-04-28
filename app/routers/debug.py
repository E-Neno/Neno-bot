import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.security import require_admin_token
from app.storage.db import fetch_all, fetch_one, list_debug_events, list_proactive_events

router = APIRouter(prefix="/debug", tags=["debug"])


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _sanitize_debug_event(event: dict) -> dict:
    return {
        "id": event.get("id"),
        "created_at": event.get("created_at"),
        "trace_id": event.get("trace_id"),
        "module": event.get("module"),
        "event": event.get("event"),
        "level": event.get("level") or "info",
        "success": None if event.get("success") is None else bool(event.get("success")),
        "skipped": None if event.get("skipped") is None else bool(event.get("skipped")),
        "action": event.get("action"),
        "reason": event.get("reason"),
        "target_label": event.get("target_label"),
        "candidate_id": event.get("candidate_id"),
        "metadata": _parse_metadata(event.get("metadata_json")),
    }


def _build_summary(events: list[dict]) -> dict:
    return {
        "total_returned": len(events),
        "latest_event_at": events[0]["created_at"] if events else None,
        "error_count": sum(
            1
            for event in events
            if event.get("level") == "error" or event.get("success") is False
        ),
        "proactive_count": sum(1 for event in events if event.get("module") == "proactive"),
        "platform_count": sum(1 for event in events if event.get("module") == "platform"),
        "chat_count": sum(1 for event in events if event.get("module") == "chat"),
        "openrouter_count": sum(1 for event in events if event.get("module") == "openrouter"),
    }


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _bool_from_db(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _explain_reason(text: str | None) -> str:
    value = str(text or "").strip()
    lower = value.lower()
    if not value:
        return ""
    if "random probability missed" in lower:
        return "随机概率未命中，本轮正常跳过"
    if "pending candidate exists" in lower or "pending qq candidate exists" in lower:
        return "已有待处理候选，自动调度不会继续生成"
    if "latest qq target is not whitelisted" in lower or "not whitelisted" in lower:
        return "最近 QQ 目标未允许，需要在主动目标里允许"
    if "outside active window" in lower:
        return "当前不在允许主动消息时间段"
    if "recent chat exists" in lower or "qq user message seen" in lower:
        return "最近刚聊过，主动消息跳过"
    if "daily limit reached" in lower or "daily sent limit reached" in lower:
        return "今日主动消息已达上限"
    if "min interval not reached" in lower or "last sent is within" in lower:
        return "距离上次主动消息还不够久"
    if "auto_send_failed" in lower or "auto send failed" in lower:
        return "自动发送失败，需要看候选和发送桥"
    if "openrouter_request_failed" in lower or "llm request failed" in lower:
        return "模型请求失败，检查 Key、额度、模型、区域或供应商错误"
    if "missing session_id" in lower:
        return "候选缺少 session_id，可能是旧候选，发送后不会进入上下文"
    if "proactive scheduler disabled" in lower or "自动主动消息未开启" in value:
        return "自动主动消息未开启，本轮不会生成或发送"
    return value


def _explain_action(action: str | None) -> str:
    value = str(action or "").strip()
    mapping = {
        "auto_send_failed": "自动发送失败，需要看候选和发送桥",
        "manual_failed": "手动发送失败，需要查看候选和发送链路",
        "auto_send_dry_run_ok": "dry_run 发送链路测试成功，未真实发送",
        "manual_send_dry_run": "手动 dry_run 发送链路测试完成，未真实发送",
        "auto_sent": "自动真实发送成功",
        "manual_sent": "手动真实发送成功",
        "generated_pending": "已生成 pending 候选",
        "skipped": "本轮按规则跳过",
    }
    return mapping.get(value, value)


def _card(
    card_id: str,
    title: str,
    level: str,
    summary: str,
    details: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> dict:
    return {
        "id": card_id,
        "title": title,
        "level": level,
        "summary": summary,
        "details": details or [],
        "suggestions": suggestions or [],
    }


def _latest_chat_stat(platform: str) -> dict | None:
    row = fetch_one(
        """
        SELECT created_at, success, error_type
        FROM chat_stats
        WHERE platform = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (platform,),
    )
    return dict(row) if row else None


def _latest_failed_chat_stat() -> dict | None:
    row = fetch_one(
        """
        SELECT platform, created_at, error_type
        FROM chat_stats
        WHERE platform IN ('qq', 'wx')
          AND success = 0
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None


def _diagnose_platform() -> dict:
    qq = _latest_chat_stat("qq")
    wx = _latest_chat_stat("wx")
    failed = _latest_failed_chat_stat()
    details = [
        f"最近 QQ 消息：{qq['created_at'] if qq else '暂无'}",
        f"最近微信消息：{wx['created_at'] if wx else '暂无'}",
    ]
    suggestions: list[str] = []

    if failed:
        details.append(f"最近平台错误：{failed.get('platform') or '-'} / {failed.get('error_type') or '-'} / {failed.get('created_at') or '-'}")
        suggestions.append("如果持续失败，检查平台入口 payload、Platform Token、后端模型调用和错误 trace。")

    if qq and qq.get("success") == 1 or wx and wx.get("success") == 1:
        level = "warn" if failed else "ok"
        summary = "最近平台消息能进入后端" if level == "ok" else "平台入口可用，但最近存在失败记录"
    elif qq or wx:
        level = "error" if failed else "warn"
        summary = "最近平台消息进入后端但未成功完成"
    else:
        level = "info"
        summary = "最近没有 QQ/微信平台消息，不一定是异常"
        suggestions.append("需要验证入口时，可从 QQ/微信发一条测试消息，或用本地 smoke test 检查 400/鉴权行为。")

    return _card("platform", "QQ/微信入口", level, summary, details, suggestions)


def _latest_debug_event(names: set[str] | None = None, module: str | None = None) -> dict | None:
    events = [_sanitize_debug_event(item) for item in list_debug_events(limit=100, module=module)]
    for item in events:
        if names is None or item.get("event") in names:
            return item
    return None


def _diagnose_model() -> dict:
    failed = _latest_debug_event({"openrouter_request_failed", "chat_turn_error"}, None)
    ok = _latest_debug_event({"openrouter_request_ok", "model_response_ok", "chat_turn_finished"}, None)
    details: list[str] = []
    suggestions: list[str] = []

    if failed:
        reason = _explain_reason(failed.get("reason") or failed.get("metadata", {}).get("error_message") or failed.get("event"))
        details.append(f"最近模型/聊天错误：{failed.get('event')} / {reason}")
        suggestions.append("检查 OpenRouter Key、额度、模型名、区域或供应商返回错误；再用 trace_id 查看完整链路。")
        return _card("model", "模型调用", "error", "最近模型或聊天链路存在失败", details, suggestions)

    if ok:
        details.append(f"最近成功事件：{ok.get('event')} / {ok.get('created_at')}")
        return _card("model", "模型调用", "ok", "最近模型调用成功", details, suggestions)

    return _card(
        "model",
        "模型调用",
        "info",
        "最近没有模型调用事件",
        ["没有 openrouter_request_ok / openrouter_request_failed / chat_turn_finished 记录"],
        ["需要验证模型链路时，可通过 Web 测试页发一条消息。"],
    )


def _latest_proactive_event() -> dict | None:
    events = list_proactive_events(limit=50)
    return dict(events[0]) if events else None


def _diagnose_proactive() -> dict:
    debug_event = _latest_debug_event(None, "proactive")
    proactive_event = _latest_proactive_event()
    details: list[str] = []
    suggestions: list[str] = []

    action = debug_event.get("action") if debug_event else proactive_event.get("action") if proactive_event else None
    reason = debug_event.get("reason") if debug_event else proactive_event.get("reason") if proactive_event else None
    candidate_id = debug_event.get("candidate_id") if debug_event else proactive_event.get("candidate_id") if proactive_event else None

    if debug_event:
        details.append(f"最近主动事件：{debug_event.get('event')} / {debug_event.get('created_at')}")
    if action:
        details.append(f"最近动作：{_explain_action(action)}")
    if reason:
        details.append(f"最近原因：{_explain_reason(reason)}")
    if candidate_id:
        details.append(f"最近候选 id：{candidate_id}")

    action_text = str(action or "").lower()
    event_text = str(debug_event.get("event") if debug_event else proactive_event.get("event_type") if proactive_event else "").lower()
    if "failed" in action_text or "failed" in event_text:
        suggestions.append("查看同 trace_id 的 debug_events，以及 neno-bridge / 候选状态。")
        return _card("proactive", "主动消息", "error", "最近主动消息链路存在失败", details, suggestions)
    if debug_event and debug_event.get("skipped") is True:
        suggestions.append("如果跳过原因是 pending 候选，先处理候选；如果是白名单，允许对应主动目标。")
        return _card("proactive", "主动消息", "warn", "最近主动调度按规则跳过", details, suggestions)
    if action in {"auto_sent", "manual_sent", "auto_send_dry_run_ok", "manual_send_dry_run"}:
        return _card("proactive", "主动消息", "ok", "最近主动消息发送链路正常", details, suggestions)
    if debug_event or proactive_event:
        return _card("proactive", "主动消息", "ok", "最近主动消息检查有记录", details, suggestions)
    return _card("proactive", "主动消息", "info", "最近没有主动消息事件", ["暂无 proactive_check/run_once 记录"], suggestions)


def _candidate_counts() -> dict:
    rows = fetch_all(
        """
        SELECT status, COUNT(*) AS count
        FROM proactive_candidates
        GROUP BY status
        """
    )
    return {str(row["status"] or "unknown"): int(row["count"] or 0) for row in rows}


def _latest_candidate() -> dict | None:
    row = fetch_one(
        """
        SELECT id, created_at, status, source, reason
        FROM proactive_candidates
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None


def _diagnose_candidates() -> dict:
    counts = _candidate_counts()
    latest = _latest_candidate()
    pending = counts.get("pending", 0)
    failed = counts.get("failed", 0)
    details = [
        f"pending 数：{pending}",
        f"failed 数：{failed}",
        f"最近候选：{latest['id']} / {latest['status']} / {latest['created_at']}" if latest else "最近候选：暂无",
    ]
    suggestions: list[str] = []

    if failed > 0:
        suggestions.append("查看 failed 候选的最近 debug_events，确认是白名单、发送桥还是上下文写入问题。")
        return _card("candidates", "候选状态", "warn", "存在失败候选，需要确认发送链路", details, suggestions)
    if pending > 0:
        suggestions.append("pending 候选会阻止自动继续生成；可发送、dry_run、丢弃或确认是否需要保留。")
        return _card("candidates", "候选状态", "warn", "已有 pending 候选，会影响自动生成", details, suggestions)
    if latest and latest.get("status") == "sent":
        return _card("candidates", "候选状态", "ok", "最近候选已发送", details, suggestions)
    if latest:
        return _card("candidates", "候选状态", "info", "存在历史候选，但当前无 pending", details, suggestions)
    return _card("candidates", "候选状态", "info", "还没有主动候选", details, suggestions)


def _diagnose_context() -> dict:
    context_saved = _latest_debug_event({"proactive_context_saved"}, "proactive")
    context_warning = _latest_debug_event({"proactive_context_save_warning"}, "proactive")
    sent_event = _latest_debug_event({"proactive_auto_sent", "proactive_manual_sent"}, "proactive")
    details: list[str] = []
    suggestions: list[str] = []

    if context_saved:
        details.append(f"最近上下文写入成功：{context_saved.get('created_at')}")
    if context_warning:
        reason = _explain_reason(context_warning.get("reason") or context_warning.get("metadata", {}).get("reason"))
        details.append(f"最近上下文写入警告：{reason}")
    if sent_event:
        details.append(f"最近真实发送事件：{sent_event.get('event')} / {sent_event.get('created_at')}")

    if context_warning:
        suggestions.append("如果提示 missing session_id，多半是旧候选；重新生成候选后再发送。")
        return _card("context", "上下文写入", "warn", "最近上下文写入有警告", details, suggestions)
    if sent_event and not context_saved:
        suggestions.append("真实发送后没有看到 context_saved，检查候选 metadata 是否包含 session_id。")
        return _card("context", "上下文写入", "warn", "真实发送后未看到上下文写入成功记录", details, suggestions)
    if context_saved:
        return _card("context", "上下文写入", "ok", "主动消息发送后能写入上下文", details, suggestions)
    return _card(
        "context",
        "上下文写入",
        "info",
        "最近没有真实发送后的上下文写入记录",
        details or ["没有 proactive_context_saved / proactive_context_save_warning 记录"],
        suggestions,
    )


def _overall(cards: list[dict]) -> dict:
    levels = [card["level"] for card in cards]
    if "error" in levels:
        return {
            "level": "error",
            "title": "发现异常",
            "summary": "最近链路中存在失败事件，需要优先查看红色诊断卡片。",
        }
    if "warn" in levels:
        return {
            "level": "warn",
            "title": "有需要注意的项目",
            "summary": "系统可运行，但存在跳过、pending 或上下文风险。",
        }
    return {
        "level": "ok",
        "title": "整体正常",
        "summary": "最近没有发现需要立即处理的异常。",
    }


@router.get("/events", dependencies=[Depends(require_admin_token)])
def debug_events(
    limit: int = Query(default=100, ge=1, le=300),
    module: str | None = Query(default=None, max_length=64),
    event: str | None = Query(default=None, max_length=128),
    trace_id: str | None = Query(default=None, max_length=64),
    level: str | None = Query(default=None, max_length=32),
):
    raw_events = list_debug_events(
        limit=limit,
        module=module,
        event=event,
        trace_id=trace_id,
        level=level,
    )
    events = [_sanitize_debug_event(item) for item in raw_events]
    return {
        "success": True,
        "events": events,
        "summary": _build_summary(events),
    }


@router.get("/diagnose", dependencies=[Depends(require_admin_token)])
def debug_diagnose():
    cards = [
        _diagnose_platform(),
        _diagnose_model(),
        _diagnose_proactive(),
        _diagnose_candidates(),
        _diagnose_context(),
    ]
    return {
        "success": True,
        "generated_at": _now_iso(),
        "overall": _overall(cards),
        "cards": cards,
    }
