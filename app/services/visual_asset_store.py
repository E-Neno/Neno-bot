from __future__ import annotations

import hashlib
import mimetypes
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.schemas import MediaAttachment
from app.storage import db as db_storage
from app.storage.db import fetch_one, get_conn
from app.utils.logging_utils import log_event


DEFAULT_VISUAL_ASSET_ROOT = Path("data") / "visual_assets"
DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024

_MIME_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


@dataclass(frozen=True)
class VisualAsset:
    id: int
    asset_uid: str
    sha256: str
    mime_type: str
    storage_path: str
    byte_size: int
    width: int | None = None
    height: int | None = None
    source: str | None = None
    original_filename: str | None = None
    deleted_at: str | None = None

    def to_attachment_metadata(self) -> dict[str, object]:
        data: dict[str, object] = {
            "kind": "image",
            "asset_uid": self.asset_uid,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }
        if self.width is not None:
            data["width"] = self.width
        if self.height is not None:
            data["height"] = self.height
        return data


class VisualAssetError(ValueError):
    pass


class VisualAssetStore:
    def __init__(
        self,
        *,
        root: Path | str = DEFAULT_VISUAL_ASSET_ROOT,
        base_dir: Path | str | None = None,
        max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    ) -> None:
        self.root = Path(root)
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.max_image_bytes = int(max_image_bytes)

    def archive_image_attachment(
        self,
        attachment: MediaAttachment,
        *,
        session_id: str,
        trace_id: str | None = None,
    ) -> VisualAsset:
        if attachment.kind != "image":
            raise VisualAssetError("attachment is not an image")
        media_path = (attachment.media_path or "").strip()
        if not media_path:
            raise VisualAssetError("image attachment has no local media_path")

        source_path = Path(media_path).expanduser()
        if not source_path.is_file():
            raise VisualAssetError("image attachment local file missing")

        image_bytes = source_path.read_bytes()
        if not image_bytes:
            raise VisualAssetError("image attachment is empty")
        if len(image_bytes) > self.max_image_bytes:
            raise VisualAssetError("image attachment is too large")

        mime_type = _resolve_image_mime_type(source_path, image_bytes, attachment.mime_type)
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        asset_uid = f"vimg_{sha256[:24]}"
        suffix = _MIME_SUFFIX[mime_type]
        target = self.root / sha256[:2] / f"{sha256}{suffix}"
        storage_path = _stable_storage_path(target, self.base_dir)
        width, height = _image_dimensions(mime_type, image_bytes)

        existing = _get_asset_by_sha256(sha256)
        if existing is not None and not existing.deleted_at:
            _ensure_archived_file(target, source_path)
            log_event(
                "visual_memory",
                "visual_asset_deduped",
                trace_id=trace_id,
                session_id=session_id,
                asset_uid=existing.asset_uid,
                source=attachment.source,
            )
            return existing

        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source_path, target)

        try:
            with get_conn() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO visual_assets (
                        asset_uid,
                        sha256,
                        mime_type,
                        storage_path,
                        byte_size,
                        width,
                        height,
                        source,
                        original_filename
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_uid,
                        sha256,
                        mime_type,
                        storage_path,
                        len(image_bytes),
                        width,
                        height,
                        attachment.source,
                        attachment.text_hint,
                    ),
                )
                asset_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            row = _get_asset_by_sha256(sha256)
            if row is None:
                raise
            return row

        asset = VisualAsset(
            id=asset_id,
            asset_uid=asset_uid,
            sha256=sha256,
            mime_type=mime_type,
            storage_path=storage_path,
            byte_size=len(image_bytes),
            width=width,
            height=height,
            source=attachment.source,
            original_filename=attachment.text_hint,
        )
        log_event(
            "visual_memory",
            "visual_asset_archived",
            trace_id=trace_id,
            session_id=session_id,
            asset_uid=asset.asset_uid,
            mime_type=mime_type,
            byte_size=asset.byte_size,
            source=attachment.source,
        )
        return asset


def _get_asset_by_sha256(sha256: str) -> VisualAsset | None:
    row = fetch_one(
        """
        SELECT id, asset_uid, sha256, mime_type, storage_path, byte_size,
               width, height, source, original_filename, deleted_at
        FROM visual_assets
        WHERE sha256 = ?
        LIMIT 1
        """,
        (sha256,),
    )
    return _asset_from_row(row)


def get_visual_asset_by_uid(asset_uid: str) -> VisualAsset | None:
    row = fetch_one(
        """
        SELECT id, asset_uid, sha256, mime_type, storage_path, byte_size,
               width, height, source, original_filename, deleted_at
        FROM visual_assets
        WHERE asset_uid = ?
        LIMIT 1
        """,
        (asset_uid,),
    )
    return _asset_from_row(row)


def add_visual_asset_link(
    *,
    asset_uid: str,
    message_id: int | None,
    session_id: str,
    trace_id: str | None,
    relation: str,
) -> bool:
    asset = get_visual_asset_by_uid(asset_uid)
    if asset is None:
        return False
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO visual_asset_links (asset_id, message_id, session_id, trace_id, relation)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asset.id, message_id, session_id, trace_id, relation),
        )
    return True


def resolve_visual_asset_path(asset: VisualAsset) -> Path:
    path = Path(asset.storage_path).expanduser()
    if path.is_file():
        return path
    if not path.is_absolute():
        candidate = Path(db_storage.DB_DIR).parent / path
        if candidate.is_file():
            return candidate
    return path


def _asset_from_row(row: object | None) -> VisualAsset | None:
    if row is None:
        return None
    return VisualAsset(
        id=int(row["id"]),
        asset_uid=str(row["asset_uid"]),
        sha256=str(row["sha256"]),
        mime_type=str(row["mime_type"]),
        storage_path=str(row["storage_path"]),
        byte_size=int(row["byte_size"]),
        width=None if row["width"] is None else int(row["width"]),
        height=None if row["height"] is None else int(row["height"]),
        source=row["source"],
        original_filename=row["original_filename"],
        deleted_at=row["deleted_at"],
    )


def _ensure_archived_file(target: Path, source_path: Path) -> None:
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)


def _stable_storage_path(target: Path, base_dir: Path) -> str:
    try:
        return target.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(target)


def _resolve_image_mime_type(path: Path, image_bytes: bytes, mime_type: str | None) -> str:
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized in _MIME_SUFFIX and _magic_matches(normalized, image_bytes):
        return normalized

    guessed, _ = mimetypes.guess_type(path.name)
    if guessed in _MIME_SUFFIX and _magic_matches(guessed, image_bytes):
        return guessed

    for candidate in _MIME_SUFFIX:
        if _magic_matches(candidate, image_bytes):
            return candidate
    raise VisualAssetError("unsupported image type")


def _magic_matches(mime_type: str, image_bytes: bytes) -> bool:
    if mime_type == "image/jpeg":
        return image_bytes.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/gif":
        return image_bytes.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP"
    if mime_type == "image/bmp":
        return image_bytes.startswith(b"BM")
    return False


def _image_dimensions(mime_type: str, image_bytes: bytes) -> tuple[int | None, int | None]:
    if mime_type == "image/png" and len(image_bytes) >= 24:
        return int.from_bytes(image_bytes[16:20], "big"), int.from_bytes(image_bytes[20:24], "big")
    if mime_type in {"image/gif", "image/webp", "image/bmp", "image/jpeg"}:
        return None, None
    return None, None
