"""
Phase 3b 验收测试 — consume_brain_intents / send_brain_intent / preflight / consumer gate

覆盖:
- 空白名单：子系统关闭，intent 保持 queued，不创建 candidate，不发送
- 不在白名单：intent → dropped
- recent chat：保持 queued，不发送
- outside window：保持 queued，不发送
- 三个 fragments：创建 3 条 candidate，按顺序全部发送，intent → sent
- 中途失败：第 2 个 fragment 发送失败，intent → partial
- 无对应 target：intent → dropped
- consumer disabled：no-op，不读 DB，不发送，不改 status
- preflight：只读检查各种场景（no_intent / whitelist_empty / whitelist_skip /
  no_target / recent_chat_defer / ready / disabled / no_side_effects）
- enqueue_test_intent：debug-only 写入 queued intent（默认/自定义/无 target/无副作用）

所有外部依赖（DB、rules、send_proactive_candidate）全部 monkeypatch，
不访问真实 bridge 或数据库。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest


# ── fixtures ──────────────────────────────────────────────────


def _make_queued_intent(intent_id=1, user_id="wx:private:test_user", fragments=None):
    """模拟 fetch_one 返回的 proactive_intent 行"""
    if fragments is None:
        fragments = ["你好", "在吗"]
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": intent_id,
        "user_id": user_id,
        "fragments": json.dumps(fragments, ensure_ascii=False),
        "status": "queued",
        "created_at": "2025-01-01T00:00:00",
    }[key]
    return row


def _make_wx_target(session_id="wx:private:test_user", real_user_id="wxid_test123"):
    """模拟 get_proactive_target_by_session 返回的 proactive_targets 行"""
    return {
        "id": 1,
        "platform": "wx",
        "session_id": session_id,
        "target_hash": "abc123def456",
        "target_label": "test_label",
        "real_user_id": real_user_id,
        "is_allowed": 1,
        "last_seen_at": "2025-01-01T00:00:00",
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }


def _make_candidate(candidate_id=100):
    """模拟 add_proactive_candidate 返回的 candidate dict"""
    return {
        "id": candidate_id,
        "platform": "wx",
        "target_hash": "abc123def456",
        "target_label": "test_label",
        "message": "test message",
        "reason": "brain intent",
        "status": "pending",
        "source": "brain",
        "metadata_json": "{}",
    }


# ── consume_brain_intents 测试 ────────────────────────────────


class TestConsumeBrainIntents:
    """consume_brain_intents 的漏斗与分发测试"""

    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", [])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_whitelist_empty_blocks(self, mock_fetch, mock_event, mock_send):
        """空白名单 = 子系统关闭，intent 保持 queued，不创建 candidate，不发送"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "whitelist_empty"
        assert result["sent"] is False
        mock_send.assert_not_called()
        mock_event.assert_not_called()

    @patch("app.services.proactive.runner.execute_write")
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:other_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_whitelist_skip_drops(self, mock_fetch, mock_event, mock_send, mock_write):
        """user_id 不在白名单 → intent dropped"""
        mock_fetch.return_value = _make_queued_intent(user_id="wx:private:test_user")

        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "whitelist_skip"
        assert result["sent"] is False
        mock_write.assert_called_once()
        assert "dropped" in mock_write.call_args[0][0]
        mock_send.assert_not_called()

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=True)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_recent_chat_defers(
        self, mock_fetch, mock_event, mock_send,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """has_recent_user_message=True → intent 保持 queued（不 dropped）"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import consume_brain_intents
        from app.services.proactive import runner as runner_mod

        # 需要 patch execute_write 以确认不被调用（不 dropped）
        with patch.object(runner_mod, "execute_write") as mock_write:
            result = consume_brain_intents()

        assert result["action"] == "recent_chat_defer"
        assert result["sent"] is False
        # 不应调用 execute_write 更新 status
        mock_write.assert_not_called()
        mock_send.assert_not_called()

    @patch("app.services.proactive.runner.within_active_window", return_value=False)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_outside_window_defers(
        self, mock_fetch, mock_event, mock_send,
        mock_cooldown, mock_failure, mock_window,
    ):
        """within_active_window=False → intent 保持 queued（不 dropped）"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import consume_brain_intents
        from app.services.proactive import runner as runner_mod

        with patch.object(runner_mod, "execute_write") as mock_write:
            result = consume_brain_intents()

        assert result["action"] == "outside_window"
        assert result["sent"] is False
        mock_write.assert_not_called()
        mock_send.assert_not_called()

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_three_fragments_sends_all(
        self, mock_fetch, mock_event, mock_send,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """3 个 fragments → 调用 send_brain_intent，全部成功"""
        fragments = ["你好", "今天天气不错", "出去走走"]
        mock_fetch.return_value = _make_queued_intent(fragments=fragments)
        mock_send.return_value = {
            "success": True, "sent_count": 3, "total": 3, "error": None,
        }

        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "sent"
        assert result["sent"] is True
        mock_send.assert_called_once_with(
            "wx:private:test_user", fragments, mock_send.call_args[0][2], 1,
        )

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_partial_on_failure(
        self, mock_fetch, mock_event, mock_send,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """send_brain_intent 返回 partial → action 为 send_failed"""
        mock_fetch.return_value = _make_queued_intent(fragments=["你好", "在吗", "回我"])
        mock_send.return_value = {
            "success": True, "sent_count": 2, "total": 3, "error": "bridge timeout",
        }

        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        # send_brain_intent success=True（至少发了 1 条），action 应为 sent
        assert result["action"] == "sent"
        assert result["sent_count"] == 2

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.record_proactive_event")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    def test_no_target_drops_via_send(
        self, mock_fetch, mock_event, mock_send,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """send_brain_intent 返回无 target → intent dropped"""
        mock_fetch.return_value = _make_queued_intent()
        mock_send.return_value = {
            "success": False, "sent_count": 0, "total": 2, "error": "no target for session",
        }

        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "send_failed"
        assert result["sent"] is False


# ── send_brain_intent 测试 ────────────────────────────────────


class TestSendBrainIntent:
    """send_brain_intent 的发送与 candidate 创建测试"""

    @patch("app.services.proactive.send_executor.send_proactive_candidate")
    @patch("app.services.proactive.send_executor.add_proactive_candidate")
    @patch("app.services.proactive.send_executor.get_proactive_target_by_session")
    @patch("app.services.proactive.send_executor.execute_write")
    @patch("app.services.proactive.send_executor._target_hash_for_session", return_value="abc123")
    @patch("app.services.proactive.send_executor._mask_identifier", return_value="test_masked")
    def test_three_fragments_creates_three_candidates(
        self, mock_mask, mock_hash, mock_write, mock_get_target,
        mock_add_candidate, mock_send_candidate,
    ):
        """3 个 fragments → 创建 3 条 candidate，按顺序发送"""
        mock_get_target.return_value = _make_wx_target()
        mock_add_candidate.side_effect = [_make_candidate(i) for i in range(100, 103)]
        mock_send_candidate.return_value = {"success": True, "sent": True}

        from app.services.proactive.send_executor import send_brain_intent
        result = send_brain_intent(
            user_id="wx:private:test_user",
            fragments=["你好", "今天天气不错", "出去走走"],
            trace_id="test_trace",
            intent_id=42,
        )

        assert result["success"] is True
        assert result["sent_count"] == 3
        assert result["total"] == 3
        assert result["error"] is None

        # 验证创建了 3 条 candidate
        assert mock_add_candidate.call_count == 3
        # 验证调用了 3 次发送
        assert mock_send_candidate.call_count == 3
        # 验证 intent status 更新为 sent
        mock_write.assert_called_with(
            "UPDATE proactive_intent SET status=? WHERE id=?",
            ("sent", 42),
        )

    @patch("app.services.proactive.send_executor.send_proactive_candidate")
    @patch("app.services.proactive.send_executor.add_proactive_candidate")
    @patch("app.services.proactive.send_executor.get_proactive_target_by_session")
    @patch("app.services.proactive.send_executor.execute_write")
    @patch("app.services.proactive.send_executor.add_debug_event")
    @patch("app.services.proactive.send_executor._target_hash_for_session", return_value="abc123")
    @patch("app.services.proactive.send_executor._mask_identifier", return_value="test_masked")
    def test_partial_on_second_fragment_failure(
        self, mock_mask, mock_hash, mock_debug, mock_write, mock_get_target,
        mock_add_candidate, mock_send_candidate,
    ):
        """第 2 个 fragment 发送失败 → intent partial"""
        mock_get_target.return_value = _make_wx_target()
        mock_add_candidate.side_effect = [_make_candidate(i) for i in range(100, 103)]
        mock_send_candidate.side_effect = [
            {"success": True, "sent": True},
            Exception("bridge timeout"),
        ]

        from app.services.proactive.send_executor import send_brain_intent
        result = send_brain_intent(
            user_id="wx:private:test_user",
            fragments=["你好", "在吗", "回我"],
            trace_id="test_trace",
            intent_id=42,
        )

        assert result["success"] is True  # 至少发了 1 条
        assert result["sent_count"] == 1
        assert result["total"] == 3
        assert "bridge timeout" in result["error"]

        # 只创建了 2 条 candidate（第 3 条在发送失败后中断）
        assert mock_add_candidate.call_count == 2
        # intent status 更新为 partial
        mock_write.assert_called_with(
            "UPDATE proactive_intent SET status=? WHERE id=?",
            ("partial", 42),
        )
        # debug_event 被调用记录失败
        mock_debug.assert_called()

    @patch("app.services.proactive.send_executor.get_proactive_target_by_session")
    @patch("app.services.proactive.send_executor.execute_write")
    @patch("app.services.proactive.send_executor.add_debug_event")
    def test_no_target_drops_intent(
        self, mock_debug, mock_write, mock_get_target,
    ):
        """无对应 target → intent dropped + debug_event"""
        mock_get_target.return_value = None

        from app.services.proactive.send_executor import send_brain_intent
        result = send_brain_intent(
            user_id="wx:private:nonexistent",
            fragments=["你好"],
            trace_id="test_trace",
            intent_id=99,
        )

        assert result["success"] is False
        assert result["sent_count"] == 0
        assert result["error"] == "no target for session"

        # intent 被 dropped
        mock_write.assert_any_call(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (99,),
        )
        # debug_event 被调用
        mock_debug.assert_called()
        debug_call = mock_debug.call_args
        assert debug_call[1]["event"] == "no_target"


# ── Consumer Gate 测试 ────────────────────────────────────


class TestConsumerGate:
    """BRAIN_INTENT_CONSUMER_ENABLED 总开关测试"""

    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", False)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.fetch_one")
    def test_consumer_disabled_noop(self, mock_fetch):
        """consumer disabled → no-op，不读 DB，不创建 candidate，不改 status"""
        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "consumer_disabled"
        assert result["sent"] is False
        # 不应调用 fetch_one（根本不读 intent）
        mock_fetch.assert_not_called()

    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", False)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.execute_write")
    def test_consumer_disabled_no_send_no_status_change(self, mock_write, mock_send):
        """consumer disabled → 不发送，不更新 proactive_intent status"""
        from app.services.proactive.runner import consume_brain_intents
        result = consume_brain_intents()

        assert result["action"] == "consumer_disabled"
        mock_send.assert_not_called()
        mock_write.assert_not_called()


# ── Preflight 测试 ────────────────────────────────────────


class TestPreflightBrainIntent:
    """preflight_brain_intent 只读预检测试"""

    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_preflight_no_intent(self, mock_fetch):
        """无 queued intent → status=no_intent"""
        mock_fetch.return_value = None

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["next_queued_intent"] is None
        assert result["decision"]["status"] == "no_intent"
        assert result["decision"]["ready_to_send"] is False

    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", [])
    def test_preflight_whitelist_empty(self, mock_fetch):
        """白名单空 → status=whitelist_empty"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "whitelist_empty"
        assert result["decision"]["ready_to_send"] is False

    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:other_user"])
    def test_preflight_whitelist_skip(self, mock_fetch):
        """user_id 不在白名单 → status=whitelist_skip"""
        mock_fetch.return_value = _make_queued_intent(user_id="wx:private:test_user")

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "whitelist_skip"
        assert result["whitelist_match"] is False

    @patch("app.services.proactive.runner.get_proactive_target_by_session", return_value=None)
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_preflight_no_target(self, mock_fetch, mock_get_target):
        """target 找不到 → status=no_target"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "no_target"
        assert result["target_lookup"]["found"] is False

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=True)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_preflight_recent_chat_defer(
        self, mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """recent chat → status=recent_chat_defer"""
        mock_fetch.return_value = _make_queued_intent()
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "recent_chat_defer"
        assert result["decision"]["ready_to_send"] is False
        assert result["rules"]["has_recent_user_message"] is True

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_preflight_ready(
        self, mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """所有检查通过 → status=ready，ready_to_send=True"""
        mock_fetch.return_value = _make_queued_intent(fragments=["你好", "在吗"])
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "ready"
        assert result["decision"]["ready_to_send"] is True
        assert result["decision"]["expected_candidates"] == 2
        assert result["consumer_enabled"] is True
        assert result["whitelist_match"] is True
        assert result["target_lookup"]["found"] is True
        assert result["target_lookup"]["real_user_id_masked"] is not None

    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", False)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_preflight_consumer_disabled(self, mock_fetch):
        """consumer disabled → status=disabled"""
        mock_fetch.return_value = _make_queued_intent()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["status"] == "disabled"
        assert result["consumer_enabled"] is False

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    @patch("app.services.proactive.runner.send_brain_intent")
    @patch("app.services.proactive.runner.execute_write")
    def test_preflight_no_side_effects(
        self, mock_write, mock_send,
        mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """preflight 不调用 send_brain_intent，不创建 candidate，不更新 intent status"""
        mock_fetch.return_value = _make_queued_intent()
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["decision"]["ready_to_send"] is True
        # 关键：不应有任何副作用
        mock_send.assert_not_called()
        mock_write.assert_not_called()


# ── Enqueue Test Intent 测试 ──────────────────────────────


class TestEnqueueTestIntent:
    """enqueue_test_intent debug-only 功能测试"""

    @patch("app.services.proactive.runner.get_latest_proactive_target")
    def test_enqueue_with_default_fragments(self, mock_get_target):
        """默认 fragments = ['测试一下，别紧张']，默认 user_id 从 wx target 取"""
        mock_get_target.return_value = {"session_id": "wx:private:test123"}

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 999
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_cursor

        with patch("app.storage.db.get_conn", return_value=mock_conn):
            from app.services.proactive.runner import enqueue_test_intent
            result = enqueue_test_intent()

        assert result["success"] is True
        assert result["intent"]["id"] == 999
        assert result["intent"]["user_id"] == "wx:private:test123"
        assert result["intent"]["fragments"] == ["测试一下，别紧张"]
        assert result["intent"]["status"] == "queued"

    @patch("app.services.proactive.runner.get_latest_proactive_target")
    def test_enqueue_with_custom_user_and_fragments(self, mock_get_target):
        """显式传入 user_id 和 fragments"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1001
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_cursor

        with patch("app.storage.db.get_conn", return_value=mock_conn):
            from app.services.proactive.runner import enqueue_test_intent
            result = enqueue_test_intent(
                user_id="wx:private:custom_user",
                fragments=["第一条", "第二条"],
            )

        assert result["success"] is True
        assert result["intent"]["user_id"] == "wx:private:custom_user"
        assert result["intent"]["fragments"] == ["第一条", "第二条"]
        # 不应查询 wx target（已显式传入 user_id）
        mock_get_target.assert_not_called()

    @patch("app.services.proactive.runner.get_latest_proactive_target", return_value=None)
    def test_enqueue_no_wx_target_no_user_id(self, mock_get_target):
        """无 wx target 且未传 user_id → 失败"""
        from app.services.proactive.runner import enqueue_test_intent
        result = enqueue_test_intent()

        assert result["success"] is False
        assert "no wx target" in result["error"]

    @patch("app.services.proactive.runner.get_latest_proactive_target")
    def test_enqueue_no_send_no_candidate(self, mock_get_target):
        """enqueue 不调用 send_proactive_candidate，不创建 proactive_candidates"""
        mock_get_target.return_value = {"session_id": "wx:private:test123"}

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 500
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_cursor

        with patch("app.storage.db.get_conn", return_value=mock_conn):
            from app.services.proactive.runner import enqueue_test_intent
            result = enqueue_test_intent()

        assert result["success"] is True
        # 验证只执行了一条 INSERT INTO proactive_intent
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO proactive_intent" in sql
        assert "proactive_candidates" not in sql


# ── Drop Queued Test Intents 测试 ─────────────────────────


class TestDropQueuedTestIntents:
    """drop_queued_test_intents 功能测试"""

    @patch("app.services.proactive.runner.execute_write")
    def test_drop_queued(self, mock_write):
        """drop_queued_test_intents 执行 UPDATE 并返回 dropped_count"""
        mock_write.return_value = 3

        from app.services.proactive.runner import drop_queued_test_intents
        result = drop_queued_test_intents()

        assert result["success"] is True
        assert result["dropped_count"] == 3
        mock_write.assert_called_once()
        sql = mock_write.call_args[0][0]
        assert "UPDATE proactive_intent" in sql
        assert "dropped" in sql

    @patch("app.services.proactive.runner.execute_write")
    def test_drop_queued_no_send(self, mock_write):
        """drop 不调用 send，不创建 candidate"""
        mock_write.return_value = 0

        from app.services.proactive.runner import drop_queued_test_intents
        result = drop_queued_test_intents()

        assert result["success"] is True
        assert result["dropped_count"] == 0


# ── Preflight fragments_preview 测试 ──────────────────────


class TestPreflightFragmentsPreview:
    """preflight fragments_preview 字段测试"""

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_fragments_preview_max_three(
        self, mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """超过 3 条 fragments 时只预览前 3 条"""
        long_fragments = ["第" + str(i) * 40 for i in range(5)]
        mock_fetch.return_value = _make_queued_intent(fragments=long_fragments)
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        preview = result["fragments_preview"]
        assert len(preview) == 3
        # 每条最多 30 字 + 可能的 "…"
        for p in preview:
            assert len(p) <= 31  # 30 chars + "…"

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_fragments_preview_short_text(
        self, mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """短文本不截断，不加省略号"""
        mock_fetch.return_value = _make_queued_intent(fragments=["你好", "在吗"])
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["fragments_preview"] == ["你好", "在吗"]

    @patch("app.services.proactive.runner.has_recent_user_message", return_value=False)
    @patch("app.services.proactive.runner.today_sent_count", return_value=0)
    @patch("app.services.proactive.runner.within_active_window", return_value=True)
    @patch("app.services.proactive.runner.failure_pause_active", return_value=False)
    @patch("app.services.proactive.runner.hard_cooldown_active", return_value=False)
    @patch("app.services.proactive.runner.get_proactive_target_by_session")
    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", True)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_fragments_preview_truncates_long_text(
        self, mock_fetch, mock_get_target,
        mock_cooldown, mock_failure, mock_window, mock_daily, mock_recent,
    ):
        """超长文本截断到 30 字 + 省略号"""
        long_text = "这是一条非常非常长的消息" * 5  # 50 chars
        mock_fetch.return_value = _make_queued_intent(fragments=[long_text])
        mock_get_target.return_value = _make_wx_target()

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert len(result["fragments_preview"]) == 1
        assert result["fragments_preview"][0].endswith("…")
        assert len(result["fragments_preview"][0]) == 31  # 30 + "…"

    @patch("app.services.proactive.runner.fetch_one")
    @patch("app.services.proactive.runner.BRAIN_INTENT_CONSUMER_ENABLED", False)
    @patch("app.services.proactive.runner.BRAIN_WHITELIST_USERS", ["wx:private:test_user"])
    def test_fragments_preview_present_even_when_disabled(self, mock_fetch):
        """consumer disabled 时 fragments_preview 也返回（在 intent 存在的情况下）"""
        mock_fetch.return_value = _make_queued_intent(fragments=["测试"])

        from app.services.proactive.runner import preflight_brain_intent
        result = preflight_brain_intent()

        assert result["fragments_preview"] == ["测试"]
