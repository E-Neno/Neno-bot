from __future__ import annotations

from pathlib import Path
from typing import Any

from app import config
from app.schemas import MediaAttachment
from app.services.visual_asset_store import VisualAsset, VisualAssetError, VisualAssetStore
from app.utils.logging_utils import log_event


def visual_memory_enabled() -> bool:
    return bool(getattr(config, "VISUAL_MEMORY_ENABLED", False))


def archive_current_turn_images(
    *,
    message: str | None,
    attachments: list[MediaAttachment],
    session_id: str,
    trace_id: str | None,
    input_record: dict[str, Any],
) -> str | None:
    if not visual_memory_enabled():
        return None

    image_attachments = [item for item in attachments if item.kind == "image"]
    if not image_attachments:
        return None

    store = VisualAssetStore(
        root=Path(str(getattr(config, "VISUAL_ASSET_ROOT", "data/visual_assets"))),
        max_image_bytes=int(getattr(config, "VISUAL_MAX_IMAGE_BYTES", 8 * 1024 * 1024)),
    )
    assets: list[VisualAsset] = []
    try:
        for attachment in image_attachments:
            assets.append(
                store.archive_image_attachment(
                    attachment,
                    session_id=session_id,
                    trace_id=trace_id,
                )
            )
    except VisualAssetError as exc:
        log_event(
            "visual_memory",
            "visual_asset_archive_failed",
            trace_id=trace_id,
            session_id=session_id,
            level="warning",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return None

    if not assets:
        return None

    asset_metadata = [asset.to_attachment_metadata() for asset in assets]
    input_record["visual_assets"] = asset_metadata
    input_record["visual"] = {
        "archived": True,
        "current_turn_view_requested": True,
        "projection_status": "text_only",
    }
    _merge_asset_uids_into_attachments(input_record, assets)
    _mark_visual_pipeline_success(input_record)
    return build_visual_text_projection(message, assets)


def build_visual_text_projection(message: str | None, assets: list[VisualAsset]) -> str:
    lines = ["[用户发送了一张图片]"]
    user_text = (message or "").strip()
    if user_text:
        lines.append(f"用户附带文字：{user_text}")
    for asset in assets:
        lines.append(f"visual_asset_id: {asset.asset_uid}")
    return "\n".join(lines)


def _merge_asset_uids_into_attachments(input_record: dict[str, Any], assets: list[VisualAsset]) -> None:
    raw_attachments = input_record.get("attachments")
    if not isinstance(raw_attachments, list):
        return
    asset_iter = iter(assets)
    for item in raw_attachments:
        if not isinstance(item, dict) or item.get("kind") != "image":
            continue
        try:
            asset = next(asset_iter)
        except StopIteration:
            return
        item["asset_uid"] = asset.asset_uid


def _mark_visual_pipeline_success(input_record: dict[str, Any]) -> None:
    pipeline = input_record.get("pipeline")
    if not isinstance(pipeline, dict):
        return
    vision = pipeline.get("vision")
    if isinstance(vision, dict):
        vision["success"] = True
    pipeline["normalization"] = {
        "status": "visual_memory_projection",
        "failed_at": None,
    }
