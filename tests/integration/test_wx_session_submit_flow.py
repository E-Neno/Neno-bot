from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from app.routers import platform as platform_router
from app.services.chat.selection_layer import fallback_decision
from app.services.relationship_service import get_relationship_state_for_api
from app.services.session_aggregation_controller import SessionAggregationController
from app.services.session_submit_controller import SessionSubmitController
from app.storage.db import get_session_messages


def _memory_result() -> dict:
    return {
        "candidate_memory": None,
        "candidate_memory_debug": None,
        "candidate_memory_decision": {
            "action": "skip",
            "reason": "test",
            "risk_level": "low",
        },
        "auto_added_memory": False,
    }


def _post_platform_message(client, payload: dict) -> tuple[int, dict]:
    response = client.post("/platform/openclaw/message", json=payload)
    return response.status_code, response.json()


class _ManualHandle:
    """Cancel handle returned by :class:`_ManualScheduler.call_later`."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _ManualScheduler:
    """Deterministic stand-in for the controller's real ``threading.Timer``.

    Production seals an aggregation batch when its window elapses on the wall
    clock. That makes the integration tests load-sensitive: whether a second
    message joins the first batch depends on whether it allocates its ticket
    before a real timer fires. This scheduler instead *stores* each window-seal
    callback and fires it only when the test explicitly calls :meth:`fire_all`,
    so batch boundaries are driven by the test rather than by thread scheduling
    and ``time.sleep``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[tuple[_ManualHandle, Callable[[], None]]] = []

    def call_later(self, delay: float, callback: Callable[[], None]) -> _ManualHandle:
        del delay  # the window length is irrelevant under manual control
        handle = _ManualHandle()
        with self._lock:
            self._pending.append((handle, callback))
        return handle

    def fire_all(self) -> int:
        """Fire every still-pending (non-cancelled) seal callback. Returns the
        number actually fired."""
        with self._lock:
            pending = self._pending
            self._pending = []
        fired = 0
        for handle, callback in pending:
            if not handle.cancelled:
                callback()
                fired += 1
        return fired


@dataclass
class _AggregationHarness:
    controller: SessionAggregationController
    scheduler: _ManualScheduler
    max_active: Callable[[], int]

    def _active_sources(self, session_id: str) -> list[dict]:
        snapshot = self.controller.get_session_snapshot(session_id=session_id)
        return snapshot["active_sources"]

    def _wait(self, predicate: Callable[[list[dict]], bool], session_id: str, *, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sources = self._active_sources(session_id)
            if predicate(sources):
                return
            time.sleep(0.005)
        raise AssertionError(
            f"aggregation condition not met within {timeout}s for {session_id}; "
            f"active_sources={self._active_sources(session_id)}"
        )

    def wait_allocated(self, session_id: str, count: int) -> None:
        """Block until at least ``count`` sources have allocated a ticket."""
        self._wait(lambda sources: len(sources) >= count, session_id)

    def wait_ready(self, session_id: str, count: int) -> None:
        """Block until at least ``count`` active sources are ``source_ready``."""
        self._wait(
            lambda sources: sum(1 for s in sources if s.get("source_state") == "source_ready") >= count,
            session_id,
        )

    def seal(self) -> int:
        """Seal every currently-open batch deterministically."""
        return self.scheduler.fire_all()


def _patch_turn_dependencies(monkeypatch, *, reply_sleep: float = 0.08) -> _AggregationHarness:
    import app.security as security
    from app.services.chat import turn_orchestrator

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
        nonlocal active
        nonlocal max_active
        del trace_id
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(reply_sleep)
            content = messages[-1]["content"]
            if isinstance(content, list):
                text = str(content[-1].get("text", ""))
                message = text.split("【对方刚说】\n", 1)[-1]
            else:
                message = str(content)
            return f"reply:{message}"
        finally:
            with lock:
                active -= 1

    scheduler = _ManualScheduler()
    controller = SessionAggregationController(window_seconds=0.05, scheduler=scheduler)

    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", fake_generate_chat_reply)
    monkeypatch.setattr(turn_orchestrator, "process_memory_candidate", lambda *args, **kwargs: _memory_result())
    monkeypatch.setattr(turn_orchestrator, "select_response_sync", lambda messages, *args, **kwargs: fallback_decision(messages))
    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(platform_router, "session_submit_controller", SessionSubmitController())
    monkeypatch.setattr(platform_router, "session_aggregation_controller", controller)
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)

    return _AggregationHarness(controller=controller, scheduler=scheduler, max_active=lambda: max_active)


def test_wx_image_then_text_is_aggregated_into_one_batch(client, monkeypatch, admin_headers):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-image-text"

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：这是一张流程图"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-image-text",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "image", "url": "https://example.com/chart.png", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-image-text",
        "chat_type": "private",
        "message": "这是什么意思",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        # 先发图片、确认它已就绪进入开放批，再发文本：保证到达序确定（图=seq1、文=seq2），
        # 且两条都在同一个尚未封口的批里。封口由 harness.seal() 显式触发，不靠真实计时器。
        image_future = executor.submit(_post_platform_message, client, image_payload)
        harness.wait_ready(session_id, 1)
        text_future = executor.submit(_post_platform_message, client, text_payload)
        harness.wait_ready(session_id, 2)
        harness.seal()

        image_status, image_data = image_future.result()
        text_status, text_data = text_future.result()

    assert image_status == 200
    assert text_status == 200
    assert image_data["reply"] == text_data["reply"]
    assert "这是什么意思" in image_data["reply"]
    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 2
    assert messages[1]["metadata"]["aggregation"]["source_count"] == 2
    assert messages[0]["trace_id"] == messages[1]["trace_id"] == messages[2]["trace_id"]
    assert messages[0]["preview_payload"]["preview"]["current_user_message"].startswith("[用户在短时间内连续发送了 2 条内容]")

    preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[0]['id']}",
        headers=admin_headers,
    )
    payload = preview_response.json()
    assert payload["preview"]["current_user_message"].startswith("[用户在短时间内连续发送了 2 条内容]")
    assert payload["message"]["metadata"]["aggregation"]["source_count"] == 2


def test_wx_text_burst_within_window_becomes_one_batch(client, monkeypatch):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-text-burst"

    payloads = [
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第一句"},
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第二句"},
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第三句"},
    ]

    with ThreadPoolExecutor(max_workers=3) as executor:
        # 逐条发出并等其就绪后再发下一条：到达序 = 发送序（seq 1/2/3），消除并发线程乱序；
        # 三条都进同一未封口批，最后统一封口 → 一个批。
        futures: list[Future] = []
        for index, payload in enumerate(payloads, start=1):
            futures.append(executor.submit(_post_platform_message, client, payload))
            harness.wait_ready(session_id, index)
        harness.seal()
        results = [future.result() for future in futures]

    assert all(status == 200 for status, _ in results)
    assert len({data["reply"] for _, data in results}) == 1
    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "user", "assistant"]
    assert [item["content"] for item in messages[:3]] == ["第一句", "第二句", "第三句"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 3
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 1


def test_wx_voice_and_text_are_aggregated_together(client, monkeypatch):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-voice-text"

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        del media_path, trace_id
        return "语音里说的是这个位置"

    monkeypatch.setattr(platform_router, "transcribe_voice", fake_transcribe_voice)

    voice_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice-text",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "voice", "media_path": "/tmp/fake.silk", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice-text",
        "chat_type": "private",
        "message": "我是说这个地方",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(_post_platform_message, client, voice_payload)
        harness.wait_ready(session_id, 1)
        text_future = executor.submit(_post_platform_message, client, text_payload)
        harness.wait_ready(session_id, 2)
        harness.seal()

        voice_status, voice_data = voice_future.result()
        text_status, text_data = text_future.result()

    assert voice_status == 200
    assert text_status == 200
    assert voice_data["reply"] == text_data["reply"]
    assert "语音里说的是这个位置" in voice_data["reply"]
    assert "我是说这个地方" in voice_data["reply"]
    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    assert messages[0]["metadata"]["message_type"] == "voice"
    assert messages[1]["metadata"]["message_type"] == "text"


def test_wx_messages_outside_window_split_into_two_batches(client, monkeypatch):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-window-split"

    with ThreadPoolExecutor(max_workers=2) as executor:
        # 第一条单独成批并封口提交（窗口"已过"语义由显式 seal 表达）；待其彻底完成后再发第二条，
        # 第二条进新批 → 两个不同批。
        first_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-window-split", "chat_type": "private", "message": "第一批"},
        )
        harness.wait_ready(session_id, 1)
        harness.seal()
        first_status, first_data = first_future.result()

        second_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-window-split", "chat_type": "private", "message": "第二批"},
        )
        harness.wait_ready(session_id, 1)
        harness.seal()
        second_status, second_data = second_future.result()

    assert first_status == 200
    assert second_status == 200
    assert first_data["reply"] != second_data["reply"]
    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["batch_id"] != messages[2]["metadata"]["aggregation"]["batch_id"]
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 2


def test_wx_batch_waits_for_slow_preprocess_before_single_submit(client, monkeypatch, admin_headers):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-slow-preprocess"
    release_image = threading.Event()

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        release_image.wait(timeout=5)
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：慢图"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-slow-preprocess",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "image", "url": "https://example.com/slow.png", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-slow-preprocess",
        "chat_type": "private",
        "message": "后补一句",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        # 图片卡在慢预处理（未就绪），文本已就绪；封口后批应停在 batch_waiting_ready 等图片，
        # 不提交。放行图片后两条合成一个批提交。
        image_future = executor.submit(_post_platform_message, client, image_payload)
        harness.wait_allocated(session_id, 1)
        text_future = executor.submit(_post_platform_message, client, text_payload)
        harness.wait_allocated(session_id, 2)
        harness.wait_ready(session_id, 1)
        harness.seal()

        snapshot_response = client.get(
            f"/debug/session-aggregation?session_id={session_id}",
            headers=admin_headers,
        )
        release_image.set()

        image_status, image_data = image_future.result()
        text_status, text_data = text_future.result()

    snapshot = snapshot_response.json()
    assert snapshot["active_batch_count"] == 1
    assert snapshot["active_batches"][0]["batch_state"] == "batch_waiting_ready"
    assert snapshot["active_batches"][0]["source_count"] == 2

    assert image_status == 200
    assert text_status == 200
    assert image_data["reply"] == text_data["reply"]
    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]


def test_wx_batches_still_submit_serially_across_windows(client, monkeypatch):
    harness = _patch_turn_dependencies(monkeypatch, reply_sleep=0.15)
    session_id = "wx:private:wx-user-two-batches"

    with ThreadPoolExecutor(max_workers=3) as executor:
        # 第一批两条合一并提交完成，再开第二批：跨批严格串行（max_active==1），
        # 且批界确定（第一批两条同 batch_id、第二批不同）。
        first_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第一批-1"},
        )
        harness.wait_ready(session_id, 1)
        second_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第一批-2"},
        )
        harness.wait_ready(session_id, 2)
        harness.seal()
        assert first_future.result()[0] == 200
        assert second_future.result()[0] == 200

        third_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第二批-1"},
        )
        harness.wait_ready(session_id, 1)
        harness.seal()
        assert third_future.result()[0] == 200

    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["batch_id"] == messages[1]["metadata"]["aggregation"]["batch_id"]
    assert messages[3]["metadata"]["aggregation"]["batch_id"] != messages[0]["metadata"]["aggregation"]["batch_id"]


def test_wx_aggregated_trace_preview_and_delete_stay_explainable(client, monkeypatch, admin_headers):
    harness = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-delete"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-delete", "chat_type": "private", "message": "先发图片说明"},
        )
        harness.wait_ready(session_id, 1)
        second_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-delete", "chat_type": "private", "message": "再补一句问题"},
        )
        harness.wait_ready(session_id, 2)
        harness.seal()

        assert first_future.result()[0] == 200
        assert second_future.result()[0] == 200

    assert harness.max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    first_trace_id = messages[0]["trace_id"]
    assert first_trace_id == messages[1]["trace_id"] == messages[2]["trace_id"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 2
    assert len(messages[0]["metadata"]["aggregation"]["source_message_ids"]) == 2

    preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[0]['id']}",
        headers=admin_headers,
    )
    preview_payload = preview_response.json()
    assert preview_payload["trace_id"] == first_trace_id
    assert preview_payload["message"]["metadata"]["aggregation"]["source_count"] == 2

    assistant_preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[2]['id']}",
        headers=admin_headers,
    )
    assert assistant_preview_response.status_code == 200
    assistant_preview = assistant_preview_response.json()
    assert assistant_preview["message"]["role"] == "assistant"
    assert assistant_preview["preview_source_message_id"] == messages[0]["id"]
    assert assistant_preview["preview_source_metadata"]["aggregation"]["source_count"] == 2

    delete_response = client.post(
        "/session/delete-message",
        json={"message_id": messages[0]["id"]},
        headers=admin_headers,
    )
    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["deleted_scope"] == "turn"
    assert deleted["trace_id"] == first_trace_id
    assert deleted["deleted_ids"] == [messages[0]["id"], messages[1]["id"], messages[2]["id"]]
    assert get_session_messages(session_id) == []
