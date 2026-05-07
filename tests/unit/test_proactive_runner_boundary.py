import pytest
from unittest.mock import patch

from app.services.proactive.runner import (
    proactive_capability_boundary,
    get_proactive_scheduler_status,
)


def test_proactive_capability_boundary():
    boundary = proactive_capability_boundary()
    
    assert "qq" in boundary["manual_candidate_platforms"]
    assert "wx" in boundary["manual_candidate_platforms"]
    
    assert "qq" in boundary["manual_send_platforms"]
    assert "wx" in boundary["manual_send_platforms"]
    
    # 核心测试：验证 auto 边界依然是 qq-first 收口，WX 没有被纳入
    assert boundary["auto_scheduler_scope"] == "qq_first"
    assert "QQ-first" in boundary["auto_scheduler_scope_label"]
    assert "WX" in boundary["auto_scheduler_summary"]
    assert "不视为 auto 平台化已完成" in boundary["auto_scheduler_summary"]


@patch("app.services.proactive.runner.today_auto_sent_count")
@patch("app.services.proactive.runner.hard_cooldown_active")
@patch("app.services.proactive.runner.consecutive_auto_failures")
@patch("app.services.proactive.runner.failure_pause_active")
@patch("app.services.proactive.runner.evaluate_proactive_rules")
@patch("app.services.proactive.runner.latest_targets_summary")
@patch("app.services.proactive.runner.today_sent_count")
@patch("app.services.proactive.runner.last_sent_at")
@patch("app.services.proactive.runner.state")
def test_get_proactive_scheduler_status(
    mock_state,
    mock_last_sent_at,
    mock_today_sent,
    mock_targets_summary,
    mock_evaluate_rules,
    mock_failure_pause,
    mock_failures,
    mock_cooldown,
    mock_auto_sent,
):
    # Mock return values to prevent hitting actual DB
    mock_auto_sent.return_value = 0
    mock_cooldown.return_value = False
    mock_failures.return_value = 0
    mock_failure_pause.return_value = False
    mock_evaluate_rules.return_value = {
        "can_send": True,
        "reason": "OK",
        "platform": "qq",
        "target_summary": {"platform": "qq"},
        "checks": []
    }
    mock_targets_summary.return_value = []
    mock_today_sent.return_value = 0
    mock_last_sent_at.return_value = None
    mock_state.scheduler_task = None
    mock_state.last_check_at = None
    mock_state.last_result = None

    status = get_proactive_scheduler_status()
    
    assert status["success"] is True
    # 校验边界属性也被合并进来了
    assert status["auto_scheduler_scope"] == "qq_first"
    assert "wx" in status["manual_send_platforms"]
    
    # 校验状态结构的完整性
    assert "mode_label" in status
    assert "mode_description" in status
    assert "can_send_now" in status
    assert status["can_send_now"]["platform"] == "qq"
