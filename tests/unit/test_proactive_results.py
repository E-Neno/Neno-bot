import pytest
from unittest.mock import patch

from app.services.proactive.result_helpers import (
    skip_result,
    observed_result,
    generated_pending_result,
    with_explained_reason,
    normalize_manual_run_result,
)


@patch("app.services.proactive.result_helpers.record_proactive_event")
@patch("app.services.proactive.result_helpers.log_event")
def test_skip_result(mock_log, mock_record):
    with patch("app.services.proactive.result_helpers.PROACTIVE_MODE", "auto"):
        result = skip_result(reason="test reason", platform="qq", trace_id="trace-1")
        
        assert result["success"] is True
        assert result["skipped"] is True
        assert result["reason"] == "test reason"
        assert result["action"] == "skipped"
        assert result["platform"] == "qq"
        assert result["proactive_mode"] == "auto"
        assert result["checks"] == []
        
        # Verify side effects
        mock_record.assert_called_once()
        mock_log.assert_called_once()


@patch("app.services.proactive.result_helpers.record_proactive_event")
@patch("app.services.proactive.result_helpers.log_event")
def test_observed_result(mock_log, mock_record):
    checks = [{"name": "test", "ok": False, "detail": "failed check", "platform": "wx"}]
    with patch("app.services.proactive.result_helpers.PROACTIVE_MODE", "observe"):
        result = observed_result(checks, trace_id="trace-2")
        
        assert result["success"] is True
        # Since 'ok' is False, would_pass is False, so skipped is True
        assert result["skipped"] is True
        assert result["action"] == "observed"
        assert result["reason"] == "failed check"
        assert result["platform"] == "wx"
        assert result["would_pass"] is False
        assert result["checks"] == checks


def test_generated_pending_result():
    candidate = {"id": 123, "platform": "qq", "target_label": "User A"}
    result = generated_pending_result(candidate, reason="test generated")
    
    assert result["success"] is True
    assert result["skipped"] is False
    assert result["action"] == "generated_pending"
    assert result["generated_pending"] is True
    assert result["candidate_id"] == 123
    assert result["platform"] == "qq"
    assert result["target_label"] == "User A"
    assert result["reason"] == "test generated"


def test_with_explained_reason():
    def mock_explain(reason):
        if "timeout" in reason:
            return "请求超时"
        return reason

    # test none
    assert with_explained_reason(None, mock_explain) is None
    
    # test reason update
    res1 = {"reason": "api timeout"}
    updated1 = with_explained_reason(res1, mock_explain)
    assert updated1["reason"] == "请求超时"
    
    # test error fallback
    res2 = {"error": "api timeout"}
    updated2 = with_explained_reason(res2, mock_explain)
    assert updated2["reason"] == "请求超时"
    assert updated2["error"] == "api timeout"


def test_normalize_manual_run_result():
    def dummy_explain(r):
        return f"explained: {r}"

    # test observed
    res = normalize_manual_run_result({"action": "observed"}, dry_run_only=False, explain_reason=dummy_explain)
    assert res["action"] == "observed"
    
    # test skipped
    res = normalize_manual_run_result({"skipped": True}, dry_run_only=False, explain_reason=dummy_explain)
    assert res["action"] == "skipped"
    
    # test failed
    res = normalize_manual_run_result({"success": False, "error": "err"}, dry_run_only=False, explain_reason=dummy_explain)
    assert res["action"] == "failed"
    assert res["reason"] == "explained: err"
    
    # test dry run map
    res = normalize_manual_run_result({"action": "auto_send_dry_run_ok", "success": True}, dry_run_only=False, explain_reason=dummy_explain)
    assert res["action"] == "dry_run_ok"

    res = normalize_manual_run_result({"action": "auto_sent", "success": True}, dry_run_only=True, explain_reason=dummy_explain)
    assert res["action"] == "dry_run_ok"
    
    # test normal success map to generated_pending
    res = normalize_manual_run_result({"action": "some_other", "success": True}, dry_run_only=False, explain_reason=dummy_explain)
    assert res["action"] == "generated_pending"
