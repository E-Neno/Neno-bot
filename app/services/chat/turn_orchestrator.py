import threading
import time
from copy import deepcopy

from app.config import (
    CHAT_MODEL_NAME, MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL,
    SELECTION_LAYER_ENABLED, SELECTION_THINKING_OFF, SELECTION_TIMEOUT,
    VOICE_SELF_ENABLED, WORLD_PRESENCE_GATE_ENABLED,
)
from app.services.chat.context_builder import build_chat_messages, load_chat_contexts
from app.services.chat.llm_gateway import generate_chat_reply
from app.services.chat.memory_candidate_service import process_memory_candidate
from app.services.chat.selection_layer import build_selection_guidance, select_response_sync
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
from app.storage.db import add_message
from app.utils.logging_utils import log_event, new_trace_id


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
        content.insert(len(content) - 1, block)  # 插到【对方刚说】之前
    elif isinstance(content, str):
        last["content"] = [block, {"type": "text", "text": content}]


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
        contexts = load_chat_contexts(session_id, message, trace_id=trace_id)
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
                deferred_ids.append(
                    add_message(
                        session_id, "user", str(record.get("content") or ""),
                        trace_id=trace_id,
                        message_type=str(record.get("message_type") or "text"),
                        source=str(record.get("source") or (input_record or {}).get("source") or "chat"),
                        metadata=meta,
                    )
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

        # 消息进世界：把「有人找我」记成她活过的一刻经历（unspoken；她回了再翻成 expressed）。
        msg_experience_id = record_incoming_message_experience(
            message, user_message_ids, trace_id=trace_id
        )

        # ── 统一判断层：醒着时所有消息（单条/一波）都走这一个判断，把她此刻全部状态喂进去 ──
        # 「回不回（含忙/累/不想回）+ 取舍」由这一个 LLM 判断综合涌现，不再分割成多套门（互补）。
        # 物理睡眠门在上面（真没意识，零 LLM，是硬底不是分割）。崩/关 → fallback 全回，绝不阻断。
        decision = None
        if SELECTION_LAYER_ENABLED and user_message_ids and MIMO_API_KEY:
            batch = [
                {"id": uid, "content": str(rec.get("content") or "")}
                for uid, rec in zip(user_message_ids, user_records)
            ]
            sel_state = {
                "state": contexts.get("self_state_context") or "",  # 此刻的你：在哪/在干嘛/累/心情/牵挂
                "self": "；".join(list_self_facts_sync(limit=6)),    # 她活成的自己（自我库）→ 判「戳到她」
                "relationship": relationship_context or "",
                "memory": "；".join(
                    str(m.get("content") or "") for m in used_memories if isinstance(m, dict)
                )[:300],
            }
            decision = select_response_sync(
                batch, sel_state,
                model_name=MIMO_MODEL, api_key=MIMO_API_KEY,
                url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
                timeout=SELECTION_TIMEOUT, extra_body=SELECTION_THINKING_OFF,
                trace_id=trace_id,
            )
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
            if len(user_message_ids) >= 2:
                _inject_selection_guidance(messages, build_selection_guidance(decision, batch))

        model_started = time.perf_counter()
        log_event(
            "chat",
            "model_request_start",
            trace_id=trace_id,
            model=CHAT_MODEL_NAME,
        )
        reply = generate_chat_reply(messages, trace_id=trace_id)
        log_event(
            "chat",
            "model_response_ok",
            trace_id=trace_id,
            reply_len=len(reply or ""),
            latency_ms=int((time.perf_counter() - model_started) * 1000),
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
    """给「已落库但还没回」的用户消息补一条回复（Phase 5：醒来/空了捡 pending）。

    用户消息此前已写库，故这里只生成并写 assistant，不再重复落库 user。
    从 history 里剔除这批 id，避免本轮消息在 prompt 中出现两次；self_state 用
    当下（刚睡醒/空下来）的状态打底，回复自然带「我看到了」的迟到感。
    """
    contexts = load_chat_contexts(session_id, message, trace_id=trace_id)
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
    )
    reply = generate_chat_reply(messages, trace_id=trace_id)
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
        "assistant_message_id": assistant_message_id,
        "used_memories": used_memories,
    }
