from __future__ import annotations

from typing import Any

from app import config
from app.schemas import MediaAttachment
from app.services.chat.llm_gateway import generate_multimodal_chat_reply
from app.services.visual_asset_store import get_visual_asset_by_uid, resolve_visual_asset_path
from app.storage.db import fetch_all, get_conn
from app.utils.logging_utils import log_event


class VisualRecallError(RuntimeError):
    pass


def search_visual_memory(
    *,
    query: str,
    session_id: str,
    limit: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    terms = _query_terms(query)
    if not terms:
        return {"candidates": []}

    bounded_limit = max(1, min(int(limit or getattr(config, "VISUAL_RECALL_MAX_CANDIDATES", 5)), 20))
    rows = fetch_all(
        """
        SELECT
            va.asset_uid,
            va.mime_type,
            va.width,
            va.height,
            va.created_at AS asset_created_at,
            val.message_id,
            val.created_at AS linked_at,
            m.content AS projection,
            m.created_at AS message_created_at
        FROM visual_asset_links val
        JOIN visual_assets va ON va.id = val.asset_id
        LEFT JOIN messages m ON m.id = val.message_id
        WHERE val.session_id = ?
          AND va.deleted_at IS NULL
        ORDER BY COALESCE(m.id, val.id) DESC
        LIMIT 100
        """,
        (session_id,),
    )

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        projection = str(row["projection"] or "")
        haystack = " ".join(
            [
                projection,
                str(row["asset_uid"] or ""),
                str(row["mime_type"] or ""),
            ]
        ).lower()
        score = sum(1 for term in terms if term in haystack)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "asset_uid": row["asset_uid"],
                    "message_id": row["message_id"],
                    "created_at": row["message_created_at"] or row["linked_at"] or row["asset_created_at"],
                    "projection": projection,
                    "mime_type": row["mime_type"],
                    "width": row["width"],
                    "height": row["height"],
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return {"candidates": [item for _, item in scored[:bounded_limit]]}


def inspect_visual_asset(
    asset_uid: str,
    *,
    question: str,
    trace_id: str | None = None,
) -> dict[str, str]:
    asset = get_visual_asset_by_uid(asset_uid)
    if asset is None:
        raise VisualRecallError("visual asset not found")
    if asset.deleted_at:
        raise VisualRecallError("visual asset was deleted")

    path = resolve_visual_asset_path(asset)
    if not path.is_file():
        raise VisualRecallError("visual asset file missing")

    cleaned_question = (question or "").strip() or "这张图里最重要的信息是什么？"
    prompt = "\n".join(
        [
            "你正在帮 Neno 回想一张历史图片。",
            "只回答当前问题需要的可见信息；不要脑补图片外的信息。",
            f"问题：{cleaned_question}",
        ]
    )
    observation = generate_multimodal_chat_reply(
        text_prompt=prompt,
        attachments=[
            MediaAttachment(
                kind="image",
                media_path=str(path),
                mime_type=asset.mime_type,
                source="visual_memory",
                asset_uid=asset.asset_uid,
            )
        ],
        trace_id=trace_id,
    ).strip()
    if not observation:
        raise VisualRecallError("visual inspection returned empty observation")

    model_name = str(getattr(config, "VISUAL_RECALL_MODEL", getattr(config, "VISION_MODEL_NAME", "")) or "")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO visual_observations (asset_id, question, observation, model, trace_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asset.id, cleaned_question, observation, model_name, trace_id),
        )
    log_event(
        "visual_memory",
        "visual_asset_inspected",
        trace_id=trace_id,
        asset_uid=asset.asset_uid,
        observation_len=len(observation),
    )
    return {
        "asset_uid": asset.asset_uid,
        "observation": observation,
        "source": "vision_model",
    }


def _query_terms(query: str) -> list[str]:
    raw = (query or "").strip().lower()
    if not raw:
        return []
    terms = [item for item in raw.replace("\n", " ").split(" ") if item]
    if len(terms) == 1 and len(raw) > 8:
        return [raw]
    return terms
