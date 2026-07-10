from pathlib import Path

import pytest

import app.storage.db as db_storage
from app.schemas import MediaAttachment
from app.storage.db import add_message, fetch_all, init_db


def _init_test_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    init_db()
    return data_dir


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (12).to_bytes(4, "big")
        + (34).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _archive_asset(tmp_path: Path):
    from app.services.visual_asset_store import VisualAssetStore

    data_dir = _init_test_db(tmp_path)
    image = tmp_path / "screen.png"
    image.write_bytes(_png_bytes())
    store = VisualAssetStore(root=data_dir / "visual_assets", base_dir=tmp_path)
    return store.archive_image_attachment(
        MediaAttachment(kind="image", media_path=str(image), mime_type="image/png", source="mobile"),
        session_id="s",
        trace_id="trace-asset",
    )


def _link_asset(asset_id: int, message_id: int, session_id: str = "s") -> None:
    with db_storage.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO visual_asset_links (asset_id, message_id, session_id, trace_id, relation)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asset_id, message_id, session_id, "trace-link", "user_sent"),
        )


def test_visual_recall_search_finds_assets_by_message_projection(tmp_path: Path):
    from app.services.visual_recall_tool import search_visual_memory

    asset = _archive_asset(tmp_path)
    message_id = add_message(
        "s",
        "user",
        f"[用户发送了一张图片]\n用户附带文字：Android 编译报错\nvisual_asset_id: {asset.asset_uid}",
        message_type="image",
    )
    _link_asset(asset.id, message_id)

    result = search_visual_memory(query="Android 报错", session_id="s", limit=5)

    assert result["candidates"][0]["asset_uid"] == asset.asset_uid
    assert result["candidates"][0]["message_id"] == message_id
    assert "Android 编译报错" in result["candidates"][0]["projection"]
    assert result["candidates"][0]["mime_type"] == "image/png"


def test_visual_recall_inspect_reads_asset_and_records_observation(tmp_path: Path, monkeypatch):
    import app.services.visual_recall_tool as tool
    from app.services.visual_recall_tool import inspect_visual_asset

    asset = _archive_asset(tmp_path)

    def fake_generate_multimodal_chat_reply(*, text_prompt, attachments, trace_id=None):
        assert "核心报错是什么" in text_prompt
        assert attachments[0].media_path
        assert attachments[0].asset_uid == asset.asset_uid
        return "核心报错是 Gradle task failed"

    monkeypatch.setattr(tool, "generate_multimodal_chat_reply", fake_generate_multimodal_chat_reply)

    result = inspect_visual_asset(asset.asset_uid, question="核心报错是什么", trace_id="trace-inspect")

    assert result["asset_uid"] == asset.asset_uid
    assert result["observation"] == "核心报错是 Gradle task failed"
    rows = fetch_all("SELECT question, observation, model FROM visual_observations")
    assert rows[0]["question"] == "核心报错是什么"
    assert rows[0]["observation"] == "核心报错是 Gradle task failed"


def test_visual_recall_inspect_rejects_deleted_asset(tmp_path: Path):
    from app.services.visual_recall_tool import VisualRecallError, inspect_visual_asset

    asset = _archive_asset(tmp_path)
    db_storage.execute_write(
        "UPDATE visual_assets SET deleted_at = CURRENT_TIMESTAMP WHERE asset_uid = ?",
        (asset.asset_uid,),
    )

    with pytest.raises(VisualRecallError):
        inspect_visual_asset(asset.asset_uid, question="还能看吗", trace_id="trace-deleted")
