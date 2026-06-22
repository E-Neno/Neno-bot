"""声音自我：从她真实回话结晶「她说话的样子」+ 攒够才刷的门 + 喂回 prompt。"""
from pathlib import Path
from unittest.mock import patch

from app.storage import db as db_storage
from app.storage.db import add_message


def _init_db(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    db_storage.DB_DIR = d
    db_storage.DB_PATH = d / "bot.db"
    db_storage.init_db()


def test_get_voice_empty_when_none(tmp_path):
    _init_db(tmp_path)
    from app.services.chat.voice_self import get_voice_context
    assert get_voice_context() == ""


def test_refresh_disabled_is_noop(tmp_path):
    _init_db(tmp_path)
    from app.services.chat import voice_self
    add_message("s", "assistant", "回复", message_type="assistant")
    with patch.object(voice_self, "VOICE_SELF_ENABLED", False):
        voice_self.maybe_refresh_voice()
    assert voice_self.get_voice_context() == ""


def test_refresh_distills_and_stores(tmp_path):
    _init_db(tmp_path)
    from app.services.chat import voice_self
    for i in range(20):
        add_message("s", "assistant", f"回复{i}", message_type="assistant")
    with patch.object(voice_self, "VOICE_SELF_ENABLED", True), \
         patch.object(voice_self, "MIMO_API_KEY", "k"), \
         patch.object(voice_self, "VOICE_SELF_MIN_NEW_REPLIES", 5), \
         patch.object(voice_self, "chat_with_openrouter",
                      return_value="她说话偏短、口语、冷的时候话少。"):
        voice_self.maybe_refresh_voice()
    assert "偏短" in voice_self.get_voice_context()


def test_gate_skips_when_not_enough_new_replies(tmp_path):
    _init_db(tmp_path)
    from app.services.chat import voice_self
    add_message("s", "assistant", "就一条", message_type="assistant")
    called = []
    with patch.object(voice_self, "VOICE_SELF_ENABLED", True), \
         patch.object(voice_self, "MIMO_API_KEY", "k"), \
         patch.object(voice_self, "VOICE_SELF_MIN_NEW_REPLIES", 15), \
         patch.object(voice_self, "chat_with_openrouter",
                      side_effect=lambda **kw: called.append(1) or "x"):
        voice_self.maybe_refresh_voice()
    assert called == []  # 不够 15 条新回复 → 不蒸馏


def test_refresh_keeps_only_latest_row(tmp_path):
    _init_db(tmp_path)
    from app.services.chat import voice_self
    from app.storage.db import fetch_all
    for i in range(40):
        add_message("s", "assistant", f"回复{i}", message_type="assistant")
    with patch.object(voice_self, "VOICE_SELF_ENABLED", True), \
         patch.object(voice_self, "MIMO_API_KEY", "k"), \
         patch.object(voice_self, "VOICE_SELF_MIN_NEW_REPLIES", 1), \
         patch.object(voice_self, "chat_with_openrouter", return_value="风格A"):
        voice_self.maybe_refresh_voice()
    # 再加新回复 + 刷一次 → 应替换，不堆积
    for i in range(40, 60):
        add_message("s", "assistant", f"回复{i}", message_type="assistant")
    with patch.object(voice_self, "VOICE_SELF_ENABLED", True), \
         patch.object(voice_self, "MIMO_API_KEY", "k"), \
         patch.object(voice_self, "VOICE_SELF_MIN_NEW_REPLIES", 1), \
         patch.object(voice_self, "chat_with_openrouter", return_value="风格B"):
        voice_self.maybe_refresh_voice()
    rows = fetch_all("SELECT content FROM long_term_memory WHERE subject = 'neno_voice'")
    assert len(rows) == 1 and rows[0]["content"] == "风格B"


def test_voice_context_renders_block():
    from app.services.chat.context_builder import build_chat_messages
    msgs, _ = build_chat_messages(history=[], message="hi", voice_context="她说话偏短、随性")
    txt = "\n".join(b["text"] for b in msgs[-1]["content"])
    assert "【你说话的调】" in txt and "她说话偏短" in txt
