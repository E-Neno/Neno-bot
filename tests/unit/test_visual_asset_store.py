from pathlib import Path

import app.storage.db as db_storage
from app.schemas import MediaAttachment
from app.storage.db import fetch_all, init_db


def _init_test_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    init_db()
    return data_dir


def _png_bytes(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_archive_local_image_dedupes_by_sha256_and_keeps_metadata_text_only(tmp_path: Path):
    from app.services.visual_asset_store import VisualAssetStore

    data_dir = _init_test_db(tmp_path)
    source = tmp_path / "incoming.png"
    source.write_bytes(_png_bytes())
    attachment = MediaAttachment(
        kind="image",
        media_path=str(source),
        mime_type="image/png",
        source="mobile",
        text_hint="screen.png",
    )

    store = VisualAssetStore(root=data_dir / "visual_assets", base_dir=tmp_path)
    first = store.archive_image_attachment(attachment, session_id="s1", trace_id="trace-a")
    second = store.archive_image_attachment(attachment, session_id="s1", trace_id="trace-b")

    assert first.asset_uid == second.asset_uid
    assert first.sha256 == second.sha256
    assert first.width == 2
    assert first.height == 3
    assert (tmp_path / first.storage_path).is_file()

    rows = fetch_all("SELECT asset_uid, sha256, storage_path FROM visual_assets")
    assert len(rows) == 1
    metadata = first.to_attachment_metadata()
    encoded = str(metadata)
    assert metadata["asset_uid"] == first.asset_uid
    assert metadata["mime_type"] == "image/png"
    assert "base64" not in encoded
    assert "data:image" not in encoded


def test_mobile_upload_pruning_does_not_delete_archived_visual_asset(tmp_path: Path, monkeypatch):
    from app.services import mobile_upload_service
    from app.services.visual_asset_store import VisualAssetStore

    data_dir = _init_test_db(tmp_path)
    monkeypatch.setattr(mobile_upload_service, "UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(mobile_upload_service, "MAX_UPLOAD_FILES_PER_KIND", 1)

    uploaded = mobile_upload_service.save_mobile_upload(
        content=_png_bytes(),
        kind="image",
        filename="first.png",
        mime_type="image/png",
    )
    store = VisualAssetStore(root=data_dir / "visual_assets", base_dir=tmp_path)
    archived = store.archive_image_attachment(uploaded, session_id="mobile:neno", trace_id="trace-prune")

    mobile_upload_service.save_mobile_upload(
        content=_png_bytes(width=4, height=5),
        kind="image",
        filename="second.png",
        mime_type="image/png",
    )

    assert not Path(uploaded.media_path or "").exists()
    assert (tmp_path / archived.storage_path).is_file()
