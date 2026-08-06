import json
import re
import threading
import time
from copy import deepcopy

from app import config
from app.schemas import MediaAttachment
from app.config import (
    CHAT_MODEL_NAME, MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL,
    EXECUTIVE_LAYER_ENABLED, EXECUTIVE_TIMEOUT, MULTILAYER_THINKING_ENABLED,
    SELECTION_LAYER_ENABLED, SELECTION_THINKING_OFF, SELECTION_TIMEOUT,
    VOICE_SELF_ENABLED, WORLD_PRESENCE_GATE_ENABLED,
)
from app.services.chat.chat_executive import (
    build_output_guidance,
    decide_chat_turn_sync,
    enforce_executive_runtime_capabilities,
)
from app.services.chat.context_builder import (
    build_chat_messages,
    build_executive_output_messages,
    load_chat_contexts,
)
from app.services.chat.inner_deliberation import deliberate_sync
from app.services.chat.llm_gateway import generate_chat_reply, resolve_multimodal_image_input
from app.services.chat.memory_candidate_service import process_memory_candidate
from app.services.chat.selection_layer import (
    build_selection_guidance,
    fallback_decision,
    select_response_sync,
)
from app.services.chat.voice_self import maybe_refresh_voice
from app.services.consciousness.memory_recall import list_self_facts_sync
from app.services.chat.preview_service import build_chat_messages_preview_from_contexts
from app.services.consciousness.presence import (
    is_physically_asleep,
    mark_message_experience_expressed,
    record_incoming_message_experience,
    stash_pending_message,
)
from app.services.relationship_service import (
    apply_relationship_update,
    get_relationship_state_for_api,
)
from app.storage.db import add_message, get_message_by_id
from app.services.visual_asset_store import (
    add_visual_asset_link,
    get_visual_asset_by_uid,
    resolve_visual_asset_path,
)
from app.services.executive_store import record_executive_decision
from app.services.visual_recall_tool import inspect_visual_asset, search_visual_memory
from app.utils.logging_utils import log_event, new_trace_id

_VISUAL_RECALL_RE = re.compile(r"<visual_recall>(.*?)</visual_recall>", re.DOTALL)


def _generate_chat_reply_with_fallback(
    messages: list[dict],
    *,
    fallback_messages: list[dict] | None = None,
    trace_id: str | None = None,
) -> str:
    """Generate from the isolated outlet; fall back to the legacy prompt on outlet failure."""
    try:
        return generate_chat_reply(messages, trace_id=trace_id)
    except Exception as exc:
        if fallback_messages is None or fallback_messages is messages:
            raise
        log_event(
            "chat", "executive_output_fallback", trace_id=trace_id,
            level="warning", error_type=type(exc).__name__, error_message=str(exc),
        )
        return generate_chat_reply(fallback_messages, trace_id=trace_id)


def _render_recent_dialogue_for_decision(history: list[dict]) -> str:
    lines: list[str] = []
    for item in (history or [])[-12:]:
        role = "对方" if item.get("role") == "user" else "你"
        content = str(item.get("content") or "").strip().replace("\n", " ")[:300]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[-2400:]


def _build_private_decision_state(
    *,
    contexts: dict,
    used_memories: list[dict],
    history: list[dict],
    relationship_context: str | None,
    trace_id: str | None,
    session_id: str,
) -> dict[str, str]:
    try:
        self_facts = "；".join(list_self_facts_sync(limit=6))
    except Exception as exc:  # noqa: BLE001 — 自我事实不可用时不能阻断回复
        self_facts = ""
        log_event(
            "chat", "decision_self_facts_warning", trace_id=trace_id,
            session_id=session_id, level="warning",
            error_type=type(exc).__name__, error_message=str(exc),
        )
    time_context = contexts.get("time_context")
    return {
        "state": str(contexts.get("self_state_context") or ""),
        "self": self_facts,
        "relationship": str(relationship_context or ""),
        "memory": "；".join(
            str(item.get("content") or "")
            for item in used_memories if isinstance(item, dict)
        )[:300],
        "time": json.dumps(time_context, ensure_ascii=False, default=str) if time_context else "",
        "past_events": str(contexts.get("past_events") or ""),
        "history_digest": str(contexts.get("history_digest") or ""),
        "recent_dialogue": _render_recent_dialogue_for_decision(history),
    }


def _inject_selection_guidance(messages: list[dict], guidance: str) -> None:
    """把取舍指导插进回复 prompt 动态区（messages[last]，历史缓存断点之后 → 缓存安全）。

    插在最后一块「【对方刚说】」**之前**，保住它永远是最后一块（wx 测试切分依赖它）。
    """
    if not messages or not guidance:
        return
    last = messages[-1]
    block = {"type": "text", "text": guidance}
    content = last.get("content")
    if isinstance(content, list) and content:
        insert_at = len(content)
        for index, item in enumerate(content):
            if isinstance(item, dict) and str(item.get("text") or "").startswith("【对方刚说】"):
                insert_at = index
                break
        content.insert(insert_at, block)  # 插到【对方刚说】之前
    elif isinstance(content, str):
        last["content"] = [block, {"type": "text", "text": content}]


def resolve_current_turn_image_inputs(
    input_record: dict | None,
    *,
    trace_id: str | None = None,
) -> list[str]:
    visual_assets = (input_record or {}).get("visual_assets")
    if not isinstance(visual_assets, list):
        return []

    image_inputs: list[str] = []
    for item in visual_assets:
        if not isinstance(item, dict):
            continue
        asset_uid = str(item.get("asset_uid") or "").strip()
        if not asset_uid:
            continue
        asset = get_visual_asset_by_uid(asset_uid)
        if asset is None or asset.deleted_at:
            continue
        try:
            image_input = resolve_multimodal_image_input(
                MediaAttachment(
                    kind="image",
                    media_path=str(resolve_visual_asset_path(asset)),
                    mime_type=asset.mime_type,
                    source="visual_memory",
                    asset_uid=asset.asset_uid,
                ),
                trace_id=trace_id,
            )
        except Exception as exc:
            log_event(
                "visual_memory",
                "current_turn_image_resolve_failed",
                trace_id=trace_id,
                asset_uid=asset_uid,
                level="warning",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            continue
        if image_input:
            image_inputs.append(image_input)
    return image_inputs


def resolve_persisted_turn_image_inputs(
    user_message_ids: list[int],
    *,
    trace_id: str | None = None,
) -> list[str]:
    """Reload archived images for a pending turn so reconsideration stays multimodal."""
    image_inputs: list[str] = []
    seen: set[str] = set()
    for message_id in user_message_ids or []:
        try:
            item = get_message_by_id(int(message_id))
        except Exception as exc:  # noqa: BLE001 — 单条坏记录不能阻断整批 pending
            log_event(
                "visual_memory", "pending_image_lookup_failed", trace_id=trace_id,
                message_id=message_id, level="warning",
                error_type=type(exc).__name__, error_message=str(exc),
            )
            continue
        metadata = item.get("metadata") if isinstance(item, dict) else None
        for value in resolve_current_turn_image_inputs(metadata, trace_id=trace_id):
            if value not in seen:
                seen.add(value)
                image_inputs.append(value)
    return image_inputs


def _link_visual_assets_for_records(
    records: list[dict],
    message_ids: list[int],
    *,
    session_id: str,
    trace_id: str | None,
    relation: str,
) -> None:
    for message_id, record in zip(message_ids, records):
        metadata = record.get("metadata") if isinstance(record, dict) else None
        visual_assets = metadata.get("visual_assets") if isinstance(metadata, dict) else None
        if not isinstance(visual_assets, list):
            continue
        for item in visual_assets:
            if not isinstance(item, dict):
                continue
            asset_uid = str(item.get("asset_uid") or "").strip()
            if not asset_uid:
                continue
            try:
                add_visual_asset_link(
                    asset_uid=asset_uid,
                    message_id=message_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    relation=relation,
                )
            except Exception as exc:
                log_event(
                    "visual_memory",
                    "visual_asset_link_failed",
                    trace_id=trace_id,
                    session_id=session_id,
                    asset_uid=asset_uid,
                    relation=relation,
                    level="warning",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )


def _maybe_run_visual_recall_loop(
    *,
    reply: str,
    messages: list[dict],
    session_id: str,
    trace_id: str | None,
) -> str:
    if not bool(getattr(config, "VISUAL_RECALL_ENABLED", False)):
        return reply
    match = _VISUAL_RECALL_RE.search(reply or "")
    if match is None:
        return reply

    try:
        payload = json.loads(match.group(1).strip())
    except Exception as exc:
        log_event(
            "visual_memory",
            "visual_recall_parse_failed",
            trace_id=trace_id,
            session_id=session_id,
            level="warning",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return reply

    query = str(payload.get("query") or "").strip()
    question = str(payload.get("question") or query or "这张图里最重要的信息是什么？").strip()
    asset_uid = str(payload.get("asset_uid") or "").strip()
    recall_text = ""
    try:
        if not asset_uid:
            search_result = search_visual_memory(
                query=query or question,
                session_id=session_id,
                limit=int(getattr(config, "VISUAL_RECALL_MAX_CANDIDATES", 5)),
            )
            candidates = search_result.get("candidates") or []
            if candidates:
                asset_uid = str(candidates[0].get("asset_uid") or "").strip()
        if asset_uid:
            inspected = inspect_visual_asset(asset_uid, question=question, trace_id=trace_id)
            recall_text = f"【视觉回想】\nasset_uid: {asset_uid}\n观察：{inspected.get('observation') or ''}"
        else:
            recall_text = "【视觉回想】\n没有找到足够匹配的历史图片。"
    except Exception as exc:
        log_event(
            "visual_memory",
            "visual_recall_failed",
            trace_id=trace_id,
            session_id=session_id,
            level="warning",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        recall_text = "【视觉回想】\n刚刚没能成功重看那张旧图，只能根据当前文字继续。"

    _inject_selection_guidance(messages, recall_text)
    return generate_chat_reply(messages, trace_id=trace_id)


def run_chat_turn(
    session_id: str,
    message: str,
    trace_id: str | None = None,
    input_record: dict | None = None,
    persist_user_messages: list[dict] | None = None,
) -> dict:
    trace_id = trace_id or new_trace_id()
    turn_started = time.perf_counter()
    log_event(
        "chat",
        "chat_turn_start",
        trace_id=trace_id,
        session_id=session_id,
        message_len=len(message or ""),
    )

    try:
        current_turn_image_inputs = resolve_current_turn_image_inputs(input_record, trace_id=trace_id)
        contexts = load_chat_contexts(
            session_id,
            message,
            trace_id=trace_id,
            current_turn_image_inputs=current_turn_image_inputs,
        )
        history = contexts["history"]
        relationship_context = contexts["relationship_context"]
        messages = contexts["messages"]
        used_memories = contexts["used_memories"]
        log_event(
            "chat",
            "recent_messages_loaded",
            trace_id=trace_id,
            session_id=session_id,
            count=len(history),
        )

        relationship_state = None
        log_event(
            "chat",
            "memories_loaded",
            trace_id=trace_id,
            session_id=session_id,
            count=len(used_memories),
        )

        # ── ④ 物理门（唯一硬门）：她睡着 = 真没看见 → 攒着，连记忆抽取都不调 LLM。──
        if WORLD_PRESENCE_GATE_ENABLED and is_physically_asleep(trace_id=trace_id):
            deferred_ids: list[int] = []
            deferred_records = persist_user_messages or [
                {
                    "content": message,
                    "message_type": str((input_record or {}).get("message_type") or "text"),
                    "source": str((input_record or {}).get("source") or "chat"),
                    "metadata": input_record or {},
                }
            ]
            for record in deferred_records:
                meta = deepcopy(record.get("metadata") or {})
                meta["world_presence_deferred"] = True
                message_id = add_message(
                    session_id, "user", str(record.get("content") or ""),
                    trace_id=trace_id,
                    message_type=str(record.get("message_type") or "text"),
                    source=str(record.get("source") or (input_record or {}).get("source") or "chat"),
                    metadata=meta,
                )
                deferred_ids.append(message_id)
            _link_visual_assets_for_records(
                deferred_records,
                deferred_ids,
                session_id=session_id,
                trace_id=trace_id,
                relation="user_sent",
            )
            # 消息进世界：记成她活过的一刻经历（睡着也算——醒后才注意到的一段经历）。
            exp_id = record_incoming_message_experience(message, deferred_ids, trace_id=trace_id)
            stash_pending_message(
                {
                    "session_id": session_id, "message": message,
                    "user_message_ids": deferred_ids, "trace_id": trace_id,
                    "experience_id": exp_id,
                    "source": str((input_record or {}).get("source") or "chat"),
                    "platform": str((input_record or {}).get("platform") or ""),
                    "chat_type": str((input_record or {}).get("chat_type") or ""),
                    "user_id": str((input_record or {}).get("user_id") or ""),
                },
                cooldown=0.0,  # 睡着没看见，醒了立刻重新考虑
                trace_id=trace_id,
            )
            log_event("chat", "presence_deferred", trace_id=trace_id,
                      session_id=session_id, reason="asleep")
            try:
                relationship_state = apply_relationship_update(session_id, message)
            except Exception:  # noqa: BLE001
                relationship_state = None
            return {
                "trace_id": trace_id,
                "user_message_id": deferred_ids[0] if deferred_ids else None,
                "user_message_ids": deferred_ids,
                "assistant_message_id": None,
                "message_type": str((input_record or {}).get("message_type") or "text"),
                "source": str((input_record or {}).get("source") or "chat"),
                "reply": "",
                "world_action": "reply_later",
                "world_reason": "asleep",
                "candidate_memory": None,
                "candidate_memory_debug": None,
                "candidate_memory_decision": None,
                "auto_added": False,
                "auto_added_memory": False,
                "used_memories": used_memories,
                "relationship_state": relationship_state,
                "relationship_context": relationship_context,
            }

        memory_result = process_memory_candidate(
            message,
            trace_id=trace_id,
            input_record=input_record,
        )
        preview = build_chat_messages_preview_from_contexts(contexts, message)
        input_record_with_memory = deepcopy(input_record or {})
        input_record_with_memory["memory_candidate_snapshot"] = memory_result.get("candidate_memory_debug")
        input_record_with_memory["memory_candidate_decision"] = memory_result.get("candidate_memory_decision")
        input_record_with_memory["memory_auto_added"] = bool(memory_result.get("auto_added_memory"))

        # 先把用户消息落库。回复由内存中的 messages 生成，不依赖落库顺序，故前移安全；
        # 这样「晚点回」时用户消息已在历史里，等她空下来再回也接得上。
        preview_payload = {
            "trace_id": trace_id,
            "session_id": session_id,
            "preview": preview,
        }
        user_message_ids: list[int] = []
        user_records = persist_user_messages or [
            {
                "content": message,
                "message_type": str((input_record or {}).get("message_type") or "text"),
                "source": str((input_record or {}).get("source") or "chat"),
                "metadata": input_record_with_memory,
            }
        ]
        for record in user_records:
            metadata = deepcopy(record.get("metadata") or {})
            metadata["memory_candidate_snapshot"] = memory_result.get("candidate_memory_debug")
            metadata["memory_candidate_decision"] = memory_result.get("candidate_memory_decision")
            metadata["memory_auto_added"] = bool(memory_result.get("auto_added_memory"))
            user_message_ids.append(
                add_message(
                    session_id,
                    "user",
                    str(record.get("content") or ""),
                    trace_id=trace_id,
                    message_type=str(record.get("message_type") or "text"),
                    source=str(record.get("source") or (input_record or {}).get("source") or "chat"),
                    metadata=metadata,
                    preview_payload=preview_payload,
                )
            )
        _link_visual_assets_for_records(
            user_records,
            user_message_ids,
            session_id=session_id,
            trace_id=trace_id,
            relation="user_sent",
        )

        # 消息进世界：把「有人找我」记成她活过的一刻经历（unspoken；她回了再翻成 expressed）。
        msg_experience_id = record_incoming_message_experience(
            message, user_message_ids, trace_id=trace_id
        )

        # ── 醒着路径：TRIAGE 只建议，主脑开启时由 Executive 唯一拍板 ──
        # 物理睡眠门在上面（真没意识，零 LLM）。任一下层崩/关都 fail-open 到正常回复。
        batch = [
            {"id": uid, "content": str(rec.get("content") or "")}
            for uid, rec in zip(user_message_ids, user_records)
        ]
        decision = fallback_decision(batch)
        decision_state: dict[str, str] = {}
        if (SELECTION_LAYER_ENABLED or EXECUTIVE_LAYER_ENABLED) and user_message_ids:
            decision_state = _build_private_decision_state(
                contexts=contexts,
                used_memories=used_memories,
                history=list(contexts.get("history") or []),
                relationship_context=relationship_context,
                trace_id=trace_id,
                session_id=session_id,
            )
            decision_state["defer_available"] = str(
                bool(WORLD_PRESENCE_GATE_ENABLED)
            ).lower()

        if SELECTION_LAYER_ENABLED and user_message_ids and MIMO_API_KEY:
            decision = select_response_sync(
                batch, decision_state,
                model_name=MIMO_MODEL, api_key=MIMO_API_KEY,
                url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
                timeout=SELECTION_TIMEOUT, extra_body=SELECTION_THINKING_OFF,
                trace_id=trace_id,
            )

        if EXECUTIVE_LAYER_ENABLED:
            impulses = []
            if MULTILAYER_THINKING_ENABLED and decision.depth == "deep":
                impulses = deliberate_sync(
                    messages=batch,
                    state=decision_state,
                    model_name=MIMO_MODEL,
                    api_key=MIMO_API_KEY,
                    url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
                    timeout=SELECTION_TIMEOUT,
                    trace_id=trace_id,
                    extra_body=SELECTION_THINKING_OFF,
                )
            executive = decide_chat_turn_sync(
                message=message,
                batch=batch,
                state=decision_state,
                triage=decision,
                impulses=impulses,
                model_name=CHAT_MODEL_NAME,
                current_turn_image_inputs=current_turn_image_inputs,
                trace_id=trace_id,
                timeout=EXECUTIVE_TIMEOUT,
            )
            raw_executive_action = executive.action
            executive = enforce_executive_runtime_capabilities(
                executive,
                can_defer=bool(WORLD_PRESENCE_GATE_ENABLED),
                fallback_message=message,
            )
            if raw_executive_action != executive.action:
                log_event(
                    "chat", "main_executive_defer_unavailable", trace_id=trace_id,
                    session_id=session_id, level="warning",
                )
            log_event(
                "chat", "main_executive_decided", trace_id=trace_id,
                session_id=session_id, action=executive.action,
                depth=decision.depth, impulse_count=len(impulses),
            )
            try:
                record_executive_decision(
                    trace_id=trace_id,
                    session_id=session_id,
                    trigger_type="chat",
                    action=executive.action,
                    depth=decision.depth,
                    decision=executive.to_dict(),
                    world_intents=executive.world_intents,
                )
            except Exception as exc:  # noqa: BLE001 — 审计落库失败不能阻断聊天
                log_event(
                    "chat", "main_executive_persist_warning", trace_id=trace_id,
                    session_id=session_id, level="warning",
                    error_type=type(exc).__name__, error_message=str(exc),
                )

            if executive.action in {"defer", "leave_unanswered"}:
                if executive.action == "defer":
                    stash_pending_message(
                        {
                            "session_id": session_id, "message": message,
                            "user_message_ids": user_message_ids, "trace_id": trace_id,
                            "experience_id": msg_experience_id,
                            "source": str((input_record or {}).get("source") or "chat"),
                            "platform": str((input_record or {}).get("platform") or ""),
                            "chat_type": str((input_record or {}).get("chat_type") or ""),
                            "user_id": str((input_record or {}).get("user_id") or ""),
                        },
                        cooldown=180.0,
                        trace_id=trace_id,
                    )
                try:
                    relationship_state = apply_relationship_update(session_id, message)
                except Exception:  # noqa: BLE001
                    relationship_state = None
                return {
                    "trace_id": trace_id,
                    "user_message_id": user_message_ids[0] if user_message_ids else None,
                    "user_message_ids": user_message_ids,
                    "assistant_message_id": None,
                    "message_type": str((input_record or {}).get("message_type") or "text"),
                    "source": str((input_record or {}).get("source") or "chat"),
                    "reply": "",
                    "world_action": (
                        "reply_later" if executive.action == "defer" else "chose_silence"
                    ),
                    "world_reason": "main_executive",
                    "candidate_memory": memory_result["candidate_memory"],
                    "candidate_memory_debug": memory_result.get("candidate_memory_debug"),
                    "candidate_memory_decision": memory_result["candidate_memory_decision"],
                    "auto_added": memory_result["auto_added_memory"],
                    "auto_added_memory": memory_result["auto_added_memory"],
                    "used_memories": used_memories,
                    "relationship_state": relationship_state,
                    "relationship_context": relationship_context,
                }

            messages = build_executive_output_messages(
                contexts=contexts,
                message=message,
                output_guidance=build_output_guidance(executive),
                current_turn_image_inputs=current_turn_image_inputs,
            )
        else:
            if not decision.should_respond:
                # 甲：她这会儿选择不回。消息已在历史里；攒进 pending → 世界「欠回复」牵挂让她之后想起。
                stash_pending_message(
                    {
                        "session_id": session_id, "message": message,
                        "user_message_ids": user_message_ids, "trace_id": trace_id,
                        "experience_id": msg_experience_id,
                        "source": str((input_record or {}).get("source") or "chat"),
                        "platform": str((input_record or {}).get("platform") or ""),
                        "chat_type": str((input_record or {}).get("chat_type") or ""),
                        "user_id": str((input_record or {}).get("user_id") or ""),
                    },
                    cooldown=180.0,  # 选择不回 → 隔一会儿再重新考虑（不是没看见，是这会儿不想）
                    trace_id=trace_id,
                )
                log_event("chat", "selection_chose_silence", trace_id=trace_id,
                          session_id=session_id, msg_count=len(user_message_ids))
                try:
                    relationship_state = apply_relationship_update(session_id, message)
                except Exception:  # noqa: BLE001
                    relationship_state = None
                return {
                    "trace_id": trace_id,
                    "user_message_id": user_message_ids[0] if user_message_ids else None,
                    "user_message_ids": user_message_ids,
                    "assistant_message_id": None,
                    "message_type": str((input_record or {}).get("message_type") or "text"),
                    "source": str((input_record or {}).get("source") or "chat"),
                    "reply": "",
                    "world_action": "chose_silence",
                    "world_reason": "selection_layer",
                    "candidate_memory": memory_result["candidate_memory"],
                    "candidate_memory_debug": memory_result.get("candidate_memory_debug"),
                    "candidate_memory_decision": memory_result["candidate_memory_decision"],
                    "auto_added": memory_result["auto_added_memory"],
                    "auto_added_memory": memory_result["auto_added_memory"],
                    "used_memories": used_memories,
                    "relationship_state": relationship_state,
                    "relationship_context": relationship_context,
                }
            # 要回 + 是一波（≥2 条）→ 把取舍指导塞进回复 prompt 动态区（缓存安全）。
            # 单条没东西可取舍，回就直接回（判断已在上面做过，这里只管多条的取舍呈现）。
            if SELECTION_LAYER_ENABLED and len(user_message_ids) >= 2:
                _inject_selection_guidance(messages, build_selection_guidance(decision, batch))

        model_started = time.perf_counter()
        log_event(
            "chat",
            "model_request_start",
            trace_id=trace_id,
            model=CHAT_MODEL_NAME,
        )
        reply = _generate_chat_reply_with_fallback(
            messages,
            fallback_messages=(contexts["messages"] if EXECUTIVE_LAYER_ENABLED else None),
            trace_id=trace_id,
        )
        reply = _maybe_run_visual_recall_loop(
            reply=reply,
            messages=messages,
            session_id=session_id,
            trace_id=trace_id,
        )
        log_event(
            "chat",
            "model_response_ok",
            trace_id=trace_id,
            reply_len=len(reply or ""),
            latency_ms=int((time.perf_counter() - model_started) * 1000),
        )
        if current_turn_image_inputs:
            _link_visual_assets_for_records(
                user_records,
                user_message_ids,
                session_id=session_id,
                trace_id=trace_id,
                relation="current_turn_viewed",
            )

        assistant_message_id = add_message(
            session_id,
            "assistant",
            reply,
            trace_id=trace_id,
            message_type="assistant",
            source=str((input_record or {}).get("source") or "chat"),
        )
        try:
            from app.services.mobile_realtime import publish_mobile_message

            publish_mobile_message(assistant_message_id)
        except Exception:  # noqa: BLE001
            pass
        # 她回应了这条消息 → 那段经历从 unspoken 翻成 expressed（已搭理）。
        mark_message_experience_expressed(msg_experience_id, trace_id=trace_id)

        # 声音自我：回复落库后，后台攒够新回复就重蒸馏「她说话的样子」（fire-and-forget，不阻塞返回）。
        if VOICE_SELF_ENABLED:
            threading.Thread(
                target=maybe_refresh_voice, args=(trace_id,), daemon=True
            ).start()

        try:
            relationship_state = apply_relationship_update(session_id, message)
        except Exception as exc:
            log_event(
                "chat",
                "relationship_update_warning",
                trace_id=trace_id,
                session_id=session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            try:
                relationship_state = get_relationship_state_for_api(session_id)
            except Exception as fallback_exc:
                log_event(
                    "chat",
                    "relationship_state_fallback_warning",
                    trace_id=trace_id,
                    session_id=session_id,
                    error_type=type(fallback_exc).__name__,
                    error_message=str(fallback_exc),
                )
                relationship_state = None

        log_event(
            "chat",
            "chat_turn_finished",
            trace_id=trace_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - turn_started) * 1000),
        )
        return {
            "trace_id": trace_id,
            "user_message_id": user_message_ids[0] if user_message_ids else None,
            "user_message_ids": user_message_ids,
            "assistant_message_id": assistant_message_id,
            "message_type": str((input_record or {}).get("message_type") or "text"),
            "source": str((input_record or {}).get("source") or "chat"),
            "reply": reply,
            "world_action": "reply_now",
            "candidate_memory": memory_result["candidate_memory"],
            "candidate_memory_debug": memory_result.get("candidate_memory_debug"),
            "candidate_memory_decision": memory_result["candidate_memory_decision"],
            "auto_added": memory_result["auto_added_memory"],
            "auto_added_memory": memory_result["auto_added_memory"],
            "used_memories": used_memories,
            "relationship_state": relationship_state,
            "relationship_context": relationship_context,
        }
    except Exception as exc:
        log_event(
            "chat",
            "chat_turn_error",
            trace_id=trace_id,
            session_id=session_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            latency_ms=int((time.perf_counter() - turn_started) * 1000),
        )
        raise


def run_chat_turn_from_persisted_user_messages(
    *,
    session_id: str,
    message: str,
    trace_id: str,
    user_message_ids: list[int],
    source: str = "chat",
) -> dict:
    """重新考虑「已落库但还没回」的消息（Phase 5：醒来/空了捡 pending）。

    用户消息此前已写库，故这里只生成并写 assistant，不再重复落库 user。
    从 history 里剔除这批 id，避免本轮消息在 prompt 中出现两次；self_state 用
    当下（刚睡醒/空下来）的状态打底。主脑仍可回复、再次延后或明确不回。
    """
    current_turn_image_inputs = resolve_persisted_turn_image_inputs(
        user_message_ids, trace_id=trace_id
    )
    contexts = load_chat_contexts(
        session_id,
        message,
        trace_id=trace_id,
        current_turn_image_inputs=current_turn_image_inputs,
    )
    # 延迟路径之前没做记忆抽取（睡着时零 LLM），醒来读到了才补上
    try:
        process_memory_candidate(message, trace_id=trace_id)
    except Exception:  # noqa: BLE001
        pass
    excluded = {int(i) for i in (user_message_ids or [])}
    history = [h for h in contexts["history"] if int(h.get("id") or 0) not in excluded]
    messages, used_memories = build_chat_messages(
        history=history,
        message=message,
        relationship_context=contexts["relationship_context"],
        time_context=contexts["time_context"],
        memory_context=contexts["memory_context"],
        history_digest=contexts["history_digest"],
        self_state_context=contexts.get("self_state_context"),
        voice_context=contexts.get("voice_context"),
        past_events=contexts.get("past_events"),
        current_turn_image_inputs=current_turn_image_inputs,
    )
    legacy_messages = messages
    reconsider_contexts = dict(contexts)
    reconsider_contexts["history"] = history
    reconsider_contexts["messages"] = messages

    if EXECUTIVE_LAYER_ENABLED:
        by_id = {
            int(item.get("id") or 0): str(item.get("content") or "")
            for item in contexts.get("history") or []
            if int(item.get("id") or 0) in excluded
        }
        batch = [
            {"id": message_id, "content": by_id.get(message_id) or message}
            for message_id in sorted(excluded)
        ] or [{"id": 0, "content": message}]
        decision_state = _build_private_decision_state(
            contexts=contexts,
            used_memories=used_memories,
            history=history,
            relationship_context=contexts.get("relationship_context"),
            trace_id=trace_id,
            session_id=session_id,
        )
        decision_state["defer_available"] = "true"
        triage = fallback_decision(batch)
        if SELECTION_LAYER_ENABLED and MIMO_API_KEY:
            triage = select_response_sync(
                batch,
                decision_state,
                model_name=MIMO_MODEL,
                api_key=MIMO_API_KEY,
                url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
                timeout=SELECTION_TIMEOUT,
                extra_body=SELECTION_THINKING_OFF,
                trace_id=trace_id,
            )
        impulses = []
        if MULTILAYER_THINKING_ENABLED and triage.depth == "deep":
            impulses = deliberate_sync(
                messages=batch,
                state=decision_state,
                model_name=MIMO_MODEL,
                api_key=MIMO_API_KEY,
                url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
                timeout=SELECTION_TIMEOUT,
                trace_id=trace_id,
                extra_body=SELECTION_THINKING_OFF,
            )
        executive = decide_chat_turn_sync(
            message=message,
            batch=batch,
            state=decision_state,
            triage=triage,
            impulses=impulses,
            model_name=CHAT_MODEL_NAME,
            current_turn_image_inputs=current_turn_image_inputs,
            trace_id=trace_id,
            timeout=EXECUTIVE_TIMEOUT,
        )
        try:
            record_executive_decision(
                trace_id=trace_id,
                session_id=session_id,
                trigger_type="pending_reconsideration",
                action=executive.action,
                depth=triage.depth,
                decision=executive.to_dict(),
                world_intents=executive.world_intents,
            )
        except Exception as exc:  # noqa: BLE001
            log_event(
                "chat", "pending_executive_persist_warning", trace_id=trace_id,
                session_id=session_id, level="warning",
                error_type=type(exc).__name__, error_message=str(exc),
            )

        if executive.action != "reply_now":
            return {
                "trace_id": trace_id,
                "reply": "",
                "deferred": executive.action == "defer",
                "unanswered": executive.action == "leave_unanswered",
                "assistant_message_id": None,
                "used_memories": used_memories,
            }
        messages = build_executive_output_messages(
            contexts=reconsider_contexts,
            message=message,
            output_guidance=build_output_guidance(executive),
            current_turn_image_inputs=current_turn_image_inputs,
        )

    reply = _generate_chat_reply_with_fallback(
        messages,
        fallback_messages=(legacy_messages if EXECUTIVE_LAYER_ENABLED else None),
        trace_id=trace_id,
    )
    reply = _maybe_run_visual_recall_loop(
        reply=reply,
        messages=messages,
        session_id=session_id,
        trace_id=trace_id,
    )
    assistant_message_id = add_message(
        session_id, "assistant", reply, trace_id=trace_id,
        message_type="assistant", source=source,
    )
    try:
        from app.services.mobile_realtime import publish_mobile_message

        publish_mobile_message(assistant_message_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        apply_relationship_update(session_id, message)
    except Exception:  # noqa: BLE001
        pass
    return {
        "trace_id": trace_id,
        "reply": reply,
        "deferred": False,
        "unanswered": False,
        "assistant_message_id": assistant_message_id,
        "used_memories": used_memories,
    }
