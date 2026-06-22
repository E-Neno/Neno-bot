"""往事（C v1）：隔久了把旧对话框成过去的事，同一场不打扰。"""
from app.services.time_context_service import build_past_context
from app.services.chat.context_builder import build_chat_messages


def test_frames_past_when_gap_large():
    g = build_past_context({"gap_minutes": 60 * 24 * 3, "gap_text": "3天", "is_new_day": True})
    assert "3天" in g and "过去的事" in g and "一天" in g  # 跨天


def test_frames_past_just_over_threshold():
    g = build_past_context({"gap_minutes": 200, "gap_text": "3小时", "is_new_day": False})
    assert "过去的事" in g and "一天" not in g  # 未跨天，不提"过了一天"


def test_empty_when_same_session():
    assert build_past_context({"gap_minutes": 5, "gap_text": "刚刚", "is_new_day": False}) == ""
    assert build_past_context({"gap_minutes": 170, "gap_text": "快3小时", "is_new_day": False}) == ""  # 不到3h
    assert build_past_context({"gap_minutes": None}) == ""
    assert build_past_context(None) == ""


def test_past_events_renders_block():
    msgs, _ = build_chat_messages(
        history=[], message="hi", past_events="你和对方上次说话已经隔了3天。"
    )
    txt = "\n".join(b["text"] for b in msgs[-1]["content"])
    assert "【往事】" in txt and "隔了3天" in txt
