from __future__ import annotations

import app.services.proactive.send_executor as se


def _patch_send_chain(monkeypatch, target=None):
    calls = {"candidates": [], "sends": []}

    def fake_target(platform, session_id):
        return target

    def fake_add_candidate(**kw):
        calls["candidates"].append(kw)
        return {"id": len(calls["candidates"])}

    def fake_send(*, candidate_id, dry_run, event_source, trace_id):
        calls["sends"].append({"candidate_id": candidate_id, "dry_run": dry_run, "event_source": event_source})
        return {"ok": True}

    monkeypatch.setattr(se, "get_proactive_target_by_session", fake_target)
    monkeypatch.setattr(se, "add_proactive_candidate", fake_add_candidate)
    monkeypatch.setattr(se, "send_proactive_candidate", fake_send)
    monkeypatch.setattr(se, "_target_hash_for_session", lambda sid: "hash")
    monkeypatch.setattr(se, "_mask_identifier", lambda x: "***")
    monkeypatch.setattr(se, "add_debug_event", lambda **kw: None)
    return calls


def test_no_target_drops(monkeypatch):
    _patch_send_chain(monkeypatch, target=None)
    out = se.send_world_expression("wx:private:u1", ["在的"], "t1", dry_run=True)
    assert out["success"] is False
    assert out["error"] == "no target for session"


def test_dry_run_builds_candidate_no_real_send(monkeypatch):
    calls = _patch_send_chain(monkeypatch, target={"real_user_id": "realu"})
    out = se.send_world_expression("wx:private:u1", ["啊我刚醒"], "t1", dry_run=True)
    assert out["success"] is True
    assert out["sent_count"] == 1
    assert calls["sends"][0]["dry_run"] is True
    assert calls["candidates"][0]["source"] == "world"
    assert calls["candidates"][0]["platform"] == "wx"


def test_real_send_passes_dry_run_false(monkeypatch):
    calls = _patch_send_chain(monkeypatch, target={"real_user_id": "realu"})
    out = se.send_world_expression("wx:private:u1", ["嗯", "等下说"], "t1", dry_run=False)
    assert out["success"] is True
    assert out["sent_count"] == 2
    assert all(s["dry_run"] is False for s in calls["sends"])
    assert all(s["event_source"] == "world" for s in calls["sends"])


def test_blank_fragments_skipped(monkeypatch):
    calls = _patch_send_chain(monkeypatch, target={"real_user_id": "realu"})
    out = se.send_world_expression("wx:private:u1", ["", "  ", "有效"], "t1", dry_run=True)
    assert out["sent_count"] == 1
    assert out["total"] == 1
