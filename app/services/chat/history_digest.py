import json
from pathlib import Path

from app.config import HISTORY_LIMIT
from app.services.chat.llm_gateway import request_model_response
from app.storage.db import add_debug_event, fetch_all
from app.utils.logging_utils import log_event

DATA_DIR = Path("data/history_digest")
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPDATE_THRESHOLD_TOKENS = 200
COMPACT_THRESHOLD_TOKENS = 10000
COMPACT_TARGET_TOKENS = 2000

COMPACT_MODEL_PRIMARY = "deepseek/deepseek-v4-flash:free"
COMPACT_MODEL_FALLBACK = "deepseek/deepseek-v4-flash"


def _digest_path(session_id: str) -> Path:
    safe = session_id.replace("/", "_").replace(":", "_")
    return DATA_DIR / f"{safe}.json"


def _estimate_tokens(text: str) -> int:
    return len(text.encode("utf-8")) // 2


def _load_digest(session_id: str) -> dict:
    path = _digest_path(session_id)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"baked_text": "", "baked_tokens": 0, "last_baked_message_id": 0, "compacted": False}


def _save_digest(session_id: str, digest: dict) -> None:
    _digest_path(session_id).write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")


def _compact_history(baked_text: str, trace_id: str | None = None, session_id: str = "") -> str | None:
    messages = [
        {
            "role": "system",
            "content": (
                "你是对话压缩助手。将以下对话记录压缩为简洁的要点摘要，"
                "保留关键信息、偏好、情绪线索、重要事件，去掉闲聊细节和重复内容。"
                "输出中文，纯文本，不要 markdown，不要编号列表。"
            ),
        },
        {"role": "user", "content": f"对话记录：\n{baked_text}"},
    ]

    for model_name in (COMPACT_MODEL_PRIMARY, COMPACT_MODEL_FALLBACK):
        try:
            result = request_model_response(
                model_name=model_name,
                messages=messages,
                timeout=30,
                trace_id=trace_id,
            )
            if model_name == COMPACT_MODEL_FALLBACK:
                add_debug_event(
                    trace_id=trace_id,
                    module="history_digest",
                    event="compact_fallback_used",
                    level="warn",
                    reason=f"primary model {COMPACT_MODEL_PRIMARY} failed, used fallback {COMPACT_MODEL_FALLBACK}",
                    metadata_json=json.dumps(
                        {"model_used": model_name, "fallback_from": COMPACT_MODEL_PRIMARY},
                        ensure_ascii=False,
                    ),
                )
            return result.strip()
        except Exception as exc:
            if model_name == COMPACT_MODEL_PRIMARY:
                log_event(
                    "digest",
                    "history_digest_compact_primary_failed",
                    trace_id=trace_id,
                    session_id=session_id,
                    model=model_name,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                continue
            add_debug_event(
                trace_id=trace_id,
                module="history_digest",
                event="compact_total_failure",
                level="critical",
                success=False,
                reason=f"both primary and fallback models failed: {type(exc).__name__}: {str(exc)[:200]}",
                metadata_json=json.dumps(
                    {"primary_model": COMPACT_MODEL_PRIMARY, "fallback_model": COMPACT_MODEL_FALLBACK},
                    ensure_ascii=False,
                ),
            )
            return None


def get_history_digest_text(session_id: str) -> str | None:
    digest = _load_digest(session_id)
    text = digest.get("baked_text", "")
    return text if text else None


def maybe_update_history_digest(
    session_id: str,
    trace_id: str | None = None,
) -> bool:
    digest = _load_digest(session_id)
    last_id = digest.get("last_baked_message_id", 0)

    rows = fetch_all(
        """
        SELECT id, role, content
        FROM messages
        WHERE session_id = ? AND id > ? AND role IN ('user', 'assistant')
        ORDER BY id ASC
        """,
        (session_id, last_id),
    )

    if not rows:
        return False

    if len(rows) <= HISTORY_LIMIT:
        return False

    rows = rows[:-HISTORY_LIMIT]

    new_lines = []
    new_chars = 0
    for row in rows:
        role_label = "用户" if row["role"] == "user" else "Neno"
        content = (row["content"] or "").replace("\n", " ")
        if content:
            new_lines.append(f"{role_label}：{content}")
            new_chars += len(content)

    if not new_lines:
        return False

    new_tokens = _estimate_tokens("\n".join(new_lines))
    if new_tokens < UPDATE_THRESHOLD_TOKENS:
        return False

    baked_text = digest.get("baked_text", "")
    if baked_text:
        baked_text += "\n"
    baked_text += "\n".join(new_lines)

    baked_tokens = _estimate_tokens(baked_text)
    compacted = digest.get("compacted", False)

    if baked_tokens > COMPACT_THRESHOLD_TOKENS and not compacted:
        log_event(
            "digest",
            "history_digest_compact_start",
            trace_id=trace_id,
            session_id=session_id,
            baked_tokens=baked_tokens,
        )
        compacted_text = _compact_history(baked_text, trace_id=trace_id, session_id=session_id)
        if compacted_text is None:
            log_event(
                "digest",
                "history_digest_compact_failed",
                trace_id=trace_id,
                session_id=session_id,
                baked_tokens=baked_tokens,
            )
            _save_digest(
                session_id,
                {
                    "baked_text": digest.get("baked_text", ""),
                    "baked_tokens": digest.get("baked_tokens", 0),
                    "last_baked_message_id": rows[-1]["id"],
                    "compacted": False,
                },
            )
            return True
        baked_text = compacted_text
        baked_tokens = _estimate_tokens(baked_text)
        compacted = True
        log_event(
            "digest",
            "history_digest_compact_done",
            trace_id=trace_id,
            session_id=session_id,
            baked_tokens=baked_tokens,
        )

    if baked_tokens > COMPACT_THRESHOLD_TOKENS * 2:
        compacted_text = _compact_history(baked_text, trace_id=trace_id, session_id=session_id)
        if compacted_text is not None:
            baked_text = compacted_text
            baked_tokens = _estimate_tokens(baked_text)

    _save_digest(
        session_id,
        {
            "baked_text": baked_text,
            "baked_tokens": baked_tokens,
            "last_baked_message_id": rows[-1]["id"],
            "compacted": compacted,
        },
    )

    log_event(
        "digest",
        "history_digest_updated",
        trace_id=trace_id,
        session_id=session_id,
        baked_tokens=baked_tokens,
        new_tokens=new_tokens,
        compacted=compacted,
    )

    return True
