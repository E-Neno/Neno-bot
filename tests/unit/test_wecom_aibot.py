import pytest

from app.integrations.wecom_aibot.protocol import (
    build_text_reply_frame,
    build_subscribe_frame,
    normalize_callback,
)
from app.integrations.wecom_aibot.dedupe import MessageDeduper


def test_build_subscribe_frame_contains_bot_credentials_without_logging_shape():
    frame = build_subscribe_frame("BOT", "SECRET", req_id="req-1")

    assert frame == {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": "req-1"},
        "body": {"bot_id": "BOT", "secret": "SECRET"},
    }


def test_build_text_reply_frame_uses_supported_markdown_message_type():
    frame = build_text_reply_frame("req-2", "你好")

    assert frame == {
        "cmd": "aibot_respond_msg",
        "headers": {"req_id": "req-2"},
        "body": {"msgtype": "markdown", "markdown": {"content": "你好"}},
    }


def test_normalize_text_callback_maps_private_session_and_preserves_reply_context():
    callback = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-9"},
        "body": {
            "aibotid": "BOT",
            "chattype": "single",
            "from": {"userid": "u-1"},
            "msgid": "m-1",
            "msgtype": "text",
            "text": {"content": "你好"},
        },
    }

    result = normalize_callback(callback)

    assert result == {
        "platform": "wecom",
        "account_id": "BOT",
        "user_id": "u-1",
        "real_user_id": "u-1",
        "chat_type": "private",
        "group_id": None,
        "session_id": "wecom:private:u-1",
        "message": "你好",
        "message_type": "text",
        "external_message_id": "m-1",
        "req_id": "req-9",
    }


def test_message_deduper_accepts_once_and_rejects_duplicates():
    deduper = MessageDeduper(max_entries=2)

    assert deduper.seen("m-1") is False
    assert deduper.seen("m-1") is True


def test_normalize_callback_rejects_non_message_callback():
    with pytest.raises(ValueError, match="unsupported callback"):
        normalize_callback({"cmd": "aibot_event_callback", "body": {}})
