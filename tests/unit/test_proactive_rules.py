import pytest
from unittest.mock import patch

from app.services.proactive.rules import (
    explain_proactive_reason,
    proactive_mode_label,
    proactive_mode_description,
    proactive_mode_effective_action,
    evaluate_proactive_rules,
)


def test_explain_proactive_reason():
    # 测试常规边界
    assert explain_proactive_reason(None) == ""
    assert explain_proactive_reason("") == ""
    
    # 测试包含关键子串的解析
    assert "随机概率" in explain_proactive_reason("Random probability missed")
    assert "时间段" in explain_proactive_reason("outside active window for proactive")
    assert "最近刚聊过" in explain_proactive_reason("recent chat exists on wx")
    assert "上限" in explain_proactive_reason("daily limit reached")
    assert "不够久" in explain_proactive_reason("last sent is within 30 min")
    assert "待处理候选" in explain_proactive_reason("pending qq candidate exists")
    assert "模式为关闭" in explain_proactive_reason("proactive mode off")
    assert "硬冷却" in explain_proactive_reason("hard cooldown active")
    assert "连续自动发送失败" in explain_proactive_reason("auto send failure pause")
    assert "暂不发送" in explain_proactive_reason("latest wx target is not allowed")
    assert "没有可用主动目标" in explain_proactive_reason("no auto target found in DB")
    
    # 测试未匹配的兜底
    assert explain_proactive_reason("some unknown reason") == "some unknown reason"


def test_proactive_mode_text_helpers():
    # 验证各种状态的 label
    assert proactive_mode_label("off") == "关闭"
    assert proactive_mode_label("observe") == "观察"
    assert proactive_mode_label("auto") == "自动真实发送"
    
    # 验证 WX 不被误表述为已完成 auto，以及 QQ-first 的描述
    auto_desc = proactive_mode_description("auto")
    assert "QQ-first" in auto_desc
    assert "WX 只保留最小链路与手动支持" in auto_desc
    assert "不视为 auto 平台化已完成" in auto_desc
    
    # 验证有效行为
    assert proactive_mode_effective_action("off") == "skip"
    assert proactive_mode_effective_action("auto") == "generate_and_send"
    assert proactive_mode_effective_action("candidate") == "generate_pending"
    assert proactive_mode_effective_action("dry_run") == "generate_and_dry_run"
    assert proactive_mode_effective_action("observe") == "observe_only"


@patch("app.services.proactive.rules.hard_cooldown_last_event")
@patch("app.services.proactive.rules.consecutive_auto_failures")
@patch("app.services.proactive.rules.within_active_window")
@patch("app.services.proactive.rules.today_sent_count")
@patch("app.services.proactive.rules.last_sent_at")
@patch("app.services.proactive.rules.latest_auto_target")
@patch("app.services.proactive.rules.has_recent_user_message")
@patch("app.services.proactive.rules.has_pending_platform_candidate")
@patch("app.services.proactive.rules.is_allowed_qq_target")
@patch("app.services.proactive.rules.today_auto_sent_count")
def test_evaluate_proactive_rules_basic_structure(
    mock_today_auto_sent_count,
    mock_is_allowed_qq_target,
    mock_has_pending,
    mock_has_recent,
    mock_latest_target,
    mock_last_sent,
    mock_today_sent,
    mock_within_window,
    mock_failures,
    mock_cooldown,
):
    # 设定 mock 返回安全值，让规则尽可能通过
    mock_cooldown.return_value = None
    mock_failures.return_value = 0
    mock_within_window.return_value = True
    mock_today_sent.return_value = 0
    mock_last_sent.return_value = None
    mock_latest_target.return_value = {"platform": "qq", "target_hash": "abc"}
    mock_has_recent.return_value = False
    mock_has_pending.return_value = False
    mock_is_allowed_qq_target.return_value = True
    mock_today_auto_sent_count.return_value = 0
    
    # 因为 config 是全局，我们不去刻意 patch PROACTIVE_MODE（它可能是 off 导致 first rule fail）
    # 但我们主要验证输出结构包含平台和摘要信息
    with patch("app.services.proactive.rules.PROACTIVE_MODE", "candidate"):
        result = evaluate_proactive_rules(include_enabled=True)
        
        assert "can_send" in result
        assert "reason" in result
        assert "platform" in result
        assert "target_summary" in result
        assert "checks" in result
        assert isinstance(result["checks"], list)
        
        # 因为在 mock 里 target 是 qq
        assert result["platform"] == "qq"
        assert result["target_summary"]["platform"] == "qq"

    # 测试 WX 不在 auto 平台化里的警告
    mock_latest_target.return_value = {"platform": "wx", "target_hash": "def"}
    with patch("app.services.proactive.rules.PROACTIVE_MODE", "auto"):
        result = evaluate_proactive_rules()
        assert result["platform"] == "wx"
        
        # 寻找 platform_permission 这一条 check
        perm_check = next((c for c in result["checks"] if c["name"] == "platform_permission"), None)
        assert perm_check is not None
        assert "WX 目标" in perm_check["detail"]
        assert "不视为 auto 平台化已完成" in perm_check["detail"]
