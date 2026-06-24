from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from uuid import uuid4

from app.schemas import MediaAttachment


UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "mobile"
ALLOWED_KINDS = {"image", "voice", "file"}
MAX_UPLOAD_BYTES = {
    "image": 8 * 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "file": 5 * 1024 * 1024,
}
MAX_UPLOAD_FILES_PER_KIND = 200


class MobileUploadError(ValueError):
    pass


def save_mobile_upload(
    *,
    content: bytes,
    kind: str,
    filename: str | None,
    mime_type: str | None,
) -> MediaAttachment:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in ALLOWED_KINDS:
        raise MobileUploadError("unsupported upload kind")

    if not content:
        raise MobileUploadError("empty upload")
    max_bytes = MAX_UPLOAD_BYTES[normalized_kind]
    if len(content) > max_bytes:
        raise MobileUploadError("upload too large")

    safe_name = _safe_filename(filename)
    resolved_mime = _resolve_mime_type(safe_name, mime_type)
    suffix = _safe_suffix(safe_name, resolved_mime)
    target_dir = UPLOAD_ROOT / normalized_kind
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(content)
    prune_mobile_uploads(target_dir)

    return MediaAttachment(
        kind=normalized_kind,
        url=public_mobile_upload_url(normalized_kind, target.name),
        media_path=str(target),
        mime_type=resolved_mime,
        source="mobile",
        text_hint=safe_name,
    )


def public_mobile_upload_url(kind: str, stored_name: str) -> str:
    return f"/mobile/uploads/{kind}/{stored_name}"


def resolve_mobile_upload_path(kind: str, stored_name: str) -> Path:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in ALLOWED_KINDS:
        raise MobileUploadError("unsupported upload kind")
    safe_name = Path(stored_name).name
    if safe_name != stored_name or not safe_name:
        raise MobileUploadError("invalid upload name")
    path = (UPLOAD_ROOT / normalized_kind / safe_name).resolve()
    root = (UPLOAD_ROOT / normalized_kind).resolve()
    if root not in path.parents:
        raise MobileUploadError("invalid upload path")
    if not path.is_file():
        raise MobileUploadError("upload not found")
    return path


def prune_mobile_uploads(target_dir: Path) -> None:
    try:
        files = [path for path in target_dir.iterdir() if path.is_file()]
    except FileNotFoundError:
        return
    excess = len(files) - int(MAX_UPLOAD_FILES_PER_KIND)
    if excess <= 0:
        return

    for path in sorted(files, key=lambda item: item.stat().st_mtime)[:excess]:
        try:
            path.unlink()
        except OSError:
            pass


def _safe_filename(filename: str | None) -> str:
    raw = Path((filename or "upload").strip()).name
    cleaned = re.sub(r"[^\w._ -]+", "_", raw).strip(" .")
    return cleaned[:120] or "upload"


def _resolve_mime_type(filename: str, mime_type: str | None) -> str:
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized != "application/octet-stream":
        return normalized
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _safe_suffix(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(mime_type) or ".bin"
    return guessed if re.fullmatch(r"\.[a-z0-9]{1,12}", guessed) else ".bin"
