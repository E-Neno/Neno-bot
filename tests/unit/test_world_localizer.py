from app.services.consciousness.world_localizer import (
    localize_action,
    maybe_suggest_action_label_with_mimo,
    suggest_action_label_with_mimo,
)
from app.services.consciousness.world_model import load_world_def, seed_world_state


def test_localize_move_to_room_phrase_uses_room_label():
    wd = load_world_def()
    st = seed_world_state(wd)

    assert localize_action(wd, st, "move to building_entrance") == "前往小区楼下"


def test_localize_bare_move_as_walk():
    wd = load_world_def()
    st = seed_world_state(wd)

    assert localize_action(wd, st, "move") == "走动"


def test_localize_move_to_room_key_uses_room_label():
    wd = load_world_def()
    st = seed_world_state(wd)

    assert localize_action(wd, st, "move_to_cafe") == "前往咖啡馆"


def test_localize_object_action_uses_object_label():
    wd = load_world_def()
    st = seed_world_state(wd)

    assert localize_action(wd, st, "check_notice_board") == "查看公告栏"


def test_localize_chinese_action_passes_through():
    wd = load_world_def()
    st = seed_world_state(wd)

    assert localize_action(wd, st, "睡觉") == "睡觉"


def test_mimo_suggestion_uses_configured_openai_compatible_endpoint(monkeypatch):
    import app.config as config

    wd = load_world_def()
    st = seed_world_state(wd)
    captured = {}

    monkeypatch.setattr(config, "MIMO_API_KEY", "test-key")
    monkeypatch.setattr(config, "MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    monkeypatch.setattr(config, "MIMO_MODEL", "mimo-v2.5-pro")
    monkeypatch.setattr(config, "MIMO_TIMEOUT", 7)

    def fake_client(api_key, url, model_name, messages, timeout, trace_id=None):
        captured.update(
            api_key=api_key,
            url=url,
            model_name=model_name,
            messages=messages,
            timeout=timeout,
            trace_id=trace_id,
        )
        return '{"label":"在窗边停留"}'

    label = suggest_action_label_with_mimo(
        wd,
        st,
        "linger_near_window_seat",
        llm_client=fake_client,
    )

    assert label == "在窗边停留"
    assert captured["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert captured["model_name"] == "mimo-v2.5-pro"
    assert captured["timeout"] == 7


def test_mimo_suggestion_is_gated_by_world_action_label_flag(monkeypatch):
    import app.config as config

    wd = load_world_def()
    st = seed_world_state(wd)
    calls = {"count": 0}

    monkeypatch.setattr(config, "WORLD_ACTION_LLM_LABEL_ENABLED", False)

    def fake_client(*args, **kwargs):
        calls["count"] += 1
        return '{"label":"不应调用"}'

    assert maybe_suggest_action_label_with_mimo(wd, st, "unknown_action", llm_client=fake_client) is None
    assert calls["count"] == 0
