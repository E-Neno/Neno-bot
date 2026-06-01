import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config import OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter
from app.routers import platform as platform_router
from app.schemas import ChatRequest
from app.security import require_admin_token
from app.services.chat.multimodal_input_service import normalize_multimodal_message
from app.services.chat.voice_asr_service import transcribe_voice, VoiceASRError
from app.services.chat_service import (
    build_chat_messages_preview,
    mask_session_id,
    request_memory_candidate,
)
from app.services.consciousness.brain import GENERATE_SYSTEM, JUDGE_SYSTEM
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.event_pool import EventPool
from app.services.memory_candidate_decision_service import decide_memory_candidate
from app.services.proactive_scheduler import get_proactive_scheduler_status
from app.storage.db import (
    fetch_all,
    fetch_one,
    get_conn,
    get_message_by_id,
    get_session_messages,
    list_debug_events,
    list_proactive_events,
)

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/chat-preview", dependencies=[Depends(require_admin_token)])
def chat_preview(req: ChatRequest):
    preview = build_chat_messages_preview(req.session_id, req.message)
    return {
        "success": True,
        "session_id_label": mask_session_id(req.session_id),
        "memory_contexts": preview.get("memory_contexts", []),
        "selected_memories": preview.get("selected_memories", []),
        "preview": preview,
    }


@router.get("/chat-preview/message", dependencies=[Depends(require_admin_token)])
def chat_preview_by_message(message_id: int = Query(..., ge=1)):
    message = get_message_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    preview_source = message
    if message.get("role") != "user":
        trace_id = message.get("trace_id")
        if not trace_id:
            raise HTTPException(status_code=404, detail="preview snapshot not found for this message")
        session_messages = get_session_messages(message["session_id"], limit=200)
        preview_source = next(
            (
                item
                for item in session_messages
                if item.get("role") == "user"
                and item.get("trace_id") == trace_id
                and isinstance((item.get("preview_payload") or {}).get("preview"), dict)
            ),
            None,
        )
        if preview_source is None:
            raise HTTPException(status_code=404, detail="preview snapshot not found for this message")

    preview_payload = preview_source.get("preview_payload") or {}
    preview = preview_payload.get("preview")
    if not isinstance(preview, dict):
        raise HTTPException(status_code=404, detail="preview snapshot not found for this message")

    metadata = message.get("metadata") or {}
    return {
        "success": True,
        "message_id": message["id"],
        "session_id": message["session_id"],
        "session_id_label": mask_session_id(message["session_id"]),
        "trace_id": message.get("trace_id"),
        "message_type": message.get("message_type") or "text",
        "source": message.get("source") or "chat",
        "message": {
            "id": message["id"],
            "role": message["role"],
            "content": message["content"],
            "created_at": message["created_at"],
            "metadata": metadata,
        },
        "preview_source_message_id": preview_source["id"],
        "preview_source_role": preview_source.get("role"),
        "preview_source_metadata": preview_source.get("metadata") or {},
        "preview": preview,
    }


@router.get("/session-submit", dependencies=[Depends(require_admin_token)])
def session_submit_snapshot(session_id: str = Query(..., max_length=128)):
    snapshot = platform_router.session_submit_controller.get_session_snapshot(session_id=session_id)
    return {
        "success": True,
        **snapshot,
        "active_count": len(snapshot["active"]),
        "recent_count": len(snapshot["recent"]),
    }


@router.get("/session-aggregation", dependencies=[Depends(require_admin_token)])
def session_aggregation_snapshot(session_id: str = Query(..., max_length=128)):
    snapshot = platform_router.session_aggregation_controller.get_session_snapshot(session_id=session_id)
    return {
        "success": True,
        **snapshot,
        "active_batch_count": len(snapshot["active_batches"]),
        "recent_batch_count": len(snapshot["recent_batches"]),
        "active_source_count": len(snapshot["active_sources"]),
        "recent_source_count": len(snapshot["recent_sources"]),
    }


@router.post("/memory-preview", dependencies=[Depends(require_admin_token)])
def memory_preview(req: ChatRequest):
    message = req.message
    attachments = req.attachments or []
    has_image_attachment = any(item.kind == "image" for item in attachments)
    has_voice_attachment = any(item.kind == "voice" for item in attachments)
    input_record = {
        "message_type": "voice" if has_voice_attachment and not has_image_attachment else "image" if has_image_attachment else "text",
        "raw_input": req.message,
        "normalized_input": req.message,
        "attachments": [item.dict() for item in attachments],
    }

    if has_voice_attachment and not has_image_attachment:
        voice_attachment = next((item for item in attachments if item.kind == "voice"), None)
        if voice_attachment and voice_attachment.media_path:
            try:
                message = transcribe_voice(voice_attachment.media_path, trace_id="debug-preview")
            except VoiceASRError:
                message = "[语音消息(未听清)]"
        else:
            message = message or "[语音消息]"

    if has_image_attachment:
        try:
            message = normalize_multimodal_message(
                message=message,
                attachments=attachments,
                trace_id="debug-preview",
            )
        except Exception:
            message = message or req.message

    input_record["normalized_input"] = message
    candidate = request_memory_candidate(message, input_record=input_record)
    decision = decide_memory_candidate(candidate)
    return {
        "success": True,
        "session_id_label": mask_session_id(req.session_id),
        "normalized_message": message,
        "candidate": candidate,
        "decision": decision,
        "similar_memories": decision.get("similar_memories", []),
        "selected_action": decision.get("action"),
        "will_auto_add": decision.get("action") == "auto_add",
    }


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
    if "proactive mode off" in lower:
        return "主动消息模式为关闭，不会自动生成或发送"
    if "hard cooldown active" in lower:
        return "硬冷却中，本轮主动调度跳过"
    if "auto send failure pause" in lower:
        return "连续自动发送失败达到阈值，自动调度暂停"
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
    status = get_proactive_scheduler_status()
    debug_event = _latest_debug_event(None, "proactive")
    proactive_event = _latest_proactive_event()
    details: list[str] = []
    suggestions: list[str] = []
    mode = status.get("proactive_mode") or "off"
    mode_label = status.get("mode_label") or mode

    details.append(f"当前模式：{mode_label} ({mode})")
    details.append(f"模式说明：{status.get('mode_description') or '-'}")
    details.append(f"当前收口边界：{status.get('auto_scheduler_scope_label') or 'QQ-first'}")
    details.append(f"能力说明：{status.get('auto_scheduler_summary') or '-'}")
    details.append(
        f"硬冷却：{'冷却中' if status.get('hard_cooldown_active') else '未触发'} / {status.get('hard_cooldown_minutes')} 分钟"
    )
    details.append(
        f"连续自动发送失败：{status.get('consecutive_auto_failures')}/{status.get('failure_pause_threshold')}"
    )
    details.append(f"今日自动真实发送：{status.get('auto_sent_today')}/{status.get('auto_send_max_per_day')}")

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
    if mode == "off":
        return _card("proactive", "主动消息", "info", "自动主动消息已关闭", details, suggestions)
    if status.get("hard_cooldown_active"):
        suggestions.append("等待硬冷却窗口结束后，自动调度才会继续生成或发送。")
        return _card("proactive", "主动消息", "warn", "主动消息处于硬冷却中", details, suggestions)
    if status.get("failure_pause_active"):
        suggestions.append("连续自动发送失败已达到阈值；先检查发送桥、白名单和最近失败事件。")
        return _card("proactive", "主动消息", "error", "连续失败暂停自动调度", details, suggestions)
    if mode == "auto":
        suggestions.append("当前模式允许自动真实发送，但本分支验收口径仍按 QQ-first。不要把 WX 视为已完成 auto 平台化。")
    if "failed" in action_text or "failed" in event_text:
        suggestions.append("查看同 trace_id 的 debug_events，以及 neno-bridge / 候选状态。")
        return _card("proactive", "主动消息", "error", "最近主动消息链路存在失败", details, suggestions)
    if debug_event and debug_event.get("skipped") is True:
        suggestions.append("如果跳过原因是 pending 候选，先处理候选；如果是 QQ 白名单，允许对应主动目标。")
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
        _diagnose_digest(),
    ]
    return {
        "success": True,
        "generated_at": _now_iso(),
        "overall": _overall(cards),
        "cards": cards,
    }


@router.get("/alerts", dependencies=[Depends(require_admin_token)])
def debug_alerts(after_id: int = Query(default=0, ge=0)):
    raw_events = list_debug_events(limit=50, level="critical")
    events = [_sanitize_debug_event(item) for item in raw_events]
    new_events = [e for e in events if int(e.get("id", 0)) > after_id]
    return {
        "success": True,
        "events": new_events,
        "has_new": len(new_events) > 0,
    }


def _diagnose_digest() -> dict:
    compact_ok = _latest_debug_event({"history_digest_compact_done"}, "history_digest")
    compact_fail = _latest_debug_event({"compact_total_failure"}, "history_digest")
    fallback = _latest_debug_event({"compact_fallback_used"}, "history_digest")
    details: list[str] = []
    suggestions: list[str] = []

    if compact_ok:
        details.append(f"最近压缩成功：{compact_ok.get('created_at')}")
    if fallback:
        details.append(f"最近使用 fallback 模型：{fallback.get('reason')}")
        suggestions.append("free 模型可能限流或不可用，检查是否需要切换为付费版。")
    if compact_fail:
        details.append(f"压缩完全失败：{compact_fail.get('reason')}")
        suggestions.append("两个模型都失败，检查 API key、网络、模型可用性。")

    if compact_fail:
        return _card("digest", "历史压缩", "error", "历史压缩失败，缓存前缀不会更新", details, suggestions)
    if fallback and not compact_ok:
        return _card("digest", "历史压缩", "warn", "free 模型失败，已用付费版替补", details, suggestions)
    if fallback:
        return _card("digest", "历史压缩", "warn", "free 模型不可用，当前使用付费版", details, suggestions)
    if compact_ok:
        return _card("digest", "历史压缩", "ok", "历史压缩正常", details, suggestions)
    return _card("digest", "历史压缩", "info", "暂无压缩记录（对话量还不够）", details, suggestions)


# ── Consciousness Panel Routes ────────────────────────────


def _get_state_json() -> dict | None:
    row = fetch_one(
        "SELECT state_json, revision, updated_at FROM agent_state WHERE id = 1 LIMIT 1"
    )
    if row is None:
        return None
    try:
        state = json.loads(row["state_json"])
    except Exception:
        return None
    state["revision"] = int(row["revision"])
    state["updated_at"] = row["updated_at"]
    return state


@router.get("/consciousness/state", dependencies=[Depends(require_admin_token)])
def consciousness_state():
    state = _get_state_json()
    if state is None:
        return {"success": True, "state": None, "message": "agent_state 表为空，consciousness 未初始化"}
    return {"success": True, "state": state}


@router.get("/consciousness/events", dependencies=[Depends(require_admin_token)])
def consciousness_events():
    rows = fetch_all(
        """SELECT id, topic_hash, priority, content, tags, mood_impact, status, created_at
           FROM event_log
           WHERE status IN ('pending', 'consumed', 'expressed')
           ORDER BY priority ASC, created_at DESC
           LIMIT 50"""
    )
    events = []
    for row in rows:
        events.append({
            "id": row["id"],
            "topic_hash": row["topic_hash"],
            "priority": int(row["priority"]),
            "content": row["content"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "mood_impact": float(row["mood_impact"]),
            "status": row["status"],
            "created_at": row["created_at"],
        })
    return {"success": True, "events": events}


@router.get("/consciousness/world", dependencies=[Depends(require_admin_token)])
def consciousness_world():
    state = _get_state_json()
    if state is None:
        return {"success": True, "weather": None, "hot_topics": [], "time_context": "", "last_perception_at": None}
    world = state.get("world") or {}
    return {
        "success": True,
        "weather": world.get("weather"),
        "hot_topics": world.get("hot_topics", []),
        "time_context": world.get("time_context", ""),
        "last_perception_at": world.get("last_perception_at"),
    }


class InjectEventRequest(BaseModel):
    content: str
    priority: int = 2
    tags: list[str] = []
    mood_impact: float = 0.0


@router.post("/consciousness/inject", dependencies=[Depends(require_admin_token)])
def consciousness_inject(req: InjectEventRequest):
    topic_hash = EventPool.make_hash_unstructured(req.content)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO event_log (topic_hash, priority, content, tags, mood_impact, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (
                topic_hash,
                req.priority,
                req.content,
                json.dumps(req.tags, ensure_ascii=False),
                req.mood_impact,
                now,
            ),
        )
    return {
        "success": True,
        "event": {
            "topic_hash": topic_hash,
            "priority": req.priority,
            "content": req.content,
            "status": "pending",
        },
    }


def _llm_call_sync(model: str, messages: list[dict], max_tokens: int, timeout: int, trace_id: str) -> str:
    return chat_with_openrouter(
        api_key=OPENROUTER_API_KEY,
        url=OPENROUTER_URL,
        model_name=model,
        messages=messages,
        timeout=timeout,
        trace_id=trace_id,
    )


@router.post("/consciousness/think", dependencies=[Depends(require_admin_token)])
async def consciousness_think():
    trace_id = f"debug_{uuid.uuid4().hex[:8]}"
    cfg = ConsciousnessConfig()

    # ── Read state ──
    state = _get_state_json()
    if state is None:
        return {"success": False, "error": "agent_state 未初始化", "trace_id": trace_id}

    energy = state.get("energy", {})
    mood = state.get("mood", {})
    desire = state.get("desire", {})
    last_interaction = state.get("last_interaction", {})

    # ── Read pending events (do NOT consume) ──
    rows = fetch_all(
        """SELECT topic_hash, priority, content, tags, mood_impact
           FROM event_log
           WHERE status = 'pending' AND priority <= 2
           ORDER BY priority ASC, created_at ASC
           LIMIT 10"""
    )
    events = []
    for row in rows:
        events.append({
            "topic_hash": row["topic_hash"],
            "priority": int(row["priority"]),
            "content": row["content"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "mood_impact": float(row["mood_impact"]),
        })

    # ── Step 1: Rule filter ──
    step1_result = "skip"
    step1_reason = ""
    if energy.get("status") == "sleeping":
        step1_reason = "energy.status=sleeping"
    elif not events:
        step1_reason = "没有 pending 事件"
    elif all(ev["priority"] == 3 for ev in events):
        step1_reason = "所有事件都是 P3，跳过"
    else:
        step1_result = "proceed"
        p0_count = sum(1 for ev in events if ev["priority"] == 0)
        step1_reason = f"energy={energy.get('value', 0):.0f} ({energy.get('status', '?')}), {len(events)} 个事件 (P0: {p0_count})"

    result = {
        "success": True,
        "trace_id": trace_id,
        "steps": {
            "step1_rule_filter": {"result": step1_result, "reason": step1_reason},
            "step2_judge": None,
            "step3_generate": None,
        },
        "state_snapshot": state,
        "events_used": events,
    }

    if step1_result == "skip":
        return result

    # ── Step 2: LLM Judge ──
    events_text = "\n".join(
        f"- [P{ev['priority']}] {ev['content']}" for ev in events
    )
    state_text = (
        f"精力: {energy.get('value', 0):.0f}/100 ({energy.get('description', '')})\n"
        f"情绪: {mood.get('label', '?')}（{mood.get('description', '')}）\n"
        f"表达欲: {desire.get('value', 0):.0f}/100\n"
        f"上次互动: {last_interaction.get('summary') or '无'}\n"
        f"互动对象: {last_interaction.get('user_id') or '无'}"
    )
    user_prompt = f"当前状态：\n{state_text}\n\n待处理事件：\n{events_text}"

    judge_result = {"success": False, "result": None, "model": cfg.judge_model, "raw_response": ""}
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                _llm_call_sync,
                model=cfg.judge_model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200,
                timeout=int(cfg.judge_llm_timeout_seconds),
                trace_id=trace_id,
            ),
            timeout=cfg.judge_llm_timeout_seconds,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        judge_result["success"] = True
        judge_result["result"] = parsed
        judge_result["raw_response"] = raw.strip()
    except (asyncio.TimeoutError, Exception) as e:
        judge_result["raw_response"] = str(e)

    result["steps"]["step2_judge"] = judge_result

    if not judge_result["success"] or not judge_result["result"] or not judge_result["result"].get("should_share"):
        return result

    # ── Step 3: LLM Generate ──
    events_text_gen = "\n".join(f"- {ev['content']}" for ev in events)
    user_prompt_gen = (
        f"精力：{energy.get('value', 0):.0f}/100\n"
        f"情绪：{mood.get('label', '?')}\n"
        f"关于对方你记得：\n（无相关记忆，调试模式）\n\n"
        f"触发你想说话的事：\n{events_text_gen}\n\n"
        f"现在用 | 分隔多条消息，自然地说："
    )

    generate_result = {"success": False, "raw_text": "", "fragments_after_split": [], "model": cfg.generate_model, "will_not_send": True}
    models = [cfg.generate_model, cfg.generate_llm_fallback]
    for model in models:
        try:
            gen_raw = await asyncio.wait_for(
                asyncio.to_thread(
                    _llm_call_sync,
                    model=model,
                    messages=[
                        {"role": "system", "content": GENERATE_SYSTEM},
                        {"role": "user", "content": user_prompt_gen},
                    ],
                    max_tokens=300,
                    timeout=int(cfg.generate_llm_timeout_seconds),
                    trace_id=trace_id,
                ),
                timeout=cfg.generate_llm_timeout_seconds,
            )
            if gen_raw and gen_raw.strip():
                generate_result["success"] = True
                generate_result["raw_text"] = gen_raw.strip()
                generate_result["model"] = model
                parts = [p.strip() for p in gen_raw.strip().split("|") if p.strip()]
                if energy.get("value", 100) < 30:
                    parts = parts[:1]
                    if parts:
                        parts[0] = parts[0][:10]
                elif energy.get("value", 100) < 60:
                    parts = parts[:3]
                else:
                    parts = parts[:cfg.max_fragments_per_burst]
                generate_result["fragments_after_split"] = parts
                break
        except (asyncio.TimeoutError, Exception) as e:
            generate_result["raw_text"] = str(e)
            generate_result["model"] = model
            continue

    result["steps"]["step3_generate"] = generate_result
    return result


@router.get("/consciousness/phase3b/preflight", dependencies=[Depends(require_admin_token)])
def phase3b_preflight():
    """
    Phase 3b 只读预检：评估"能不能安全发送"。
    不发送、不创建 candidate、不改 status、不写 debug_events。
    """
    from app.services.proactive.runner import preflight_brain_intent
    return {
        "success": True,
        **preflight_brain_intent(),
    }


class EnqueueTestIntentRequest(BaseModel):
    user_id: str | None = None
    fragments: list[str] | None = None


@router.post("/consciousness/phase3b/enqueue_test_intent", dependencies=[Depends(require_admin_token)])
def enqueue_test_intent(req: EnqueueTestIntentRequest | None = None):
    """
    Debug-only：往 proactive_intent 写入一条 queued 测试意图。
    不发送、不创建 candidate、不调用 send_proactive_candidate。
    """
    from app.services.proactive.runner import enqueue_test_intent as _enqueue
    return _enqueue(
        user_id=req.user_id if req else None,
        fragments=req.fragments if req else None,
    )


@router.post("/consciousness/phase3b/drop_queued_test_intents", dependencies=[Depends(require_admin_token)])
def drop_queued_test_intents():
    """
    Debug-only：将所有 queued intent 标记为 dropped。
    不发送、不创建 candidate、不调用 send_proactive_candidate。
    用于灰度前清理测试 intent。
    """
    from app.services.proactive.runner import drop_queued_test_intents as _drop
    return _drop()
