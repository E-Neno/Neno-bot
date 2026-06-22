from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.models import NenoState
from app.services.consciousness.world_model import load_world_def, seed_world_state


def _state(*, location: str = "living_room", action: str = "画画"):
    ws = seed_world_state(load_world_def())
    ws.location = location
    ws.last_tick = {"action": action}
    nstate = NenoState()
    nstate.energy.status = "awake"
    nstate.mood.valence = 0.3
    return ws, nstate


def test_seed_has_exactly_four_approved_keys():
    seed = json.loads(Path("prompts/seed.json").read_text(encoding="utf-8"))
    assert set(seed) == {"name", "age", "temperament", "background_principle"}
    system_prompt = Path("prompts/system.txt").read_text(encoding="utf-8")
    assert "20岁出头" not in system_prompt
    assert "大学在读" not in system_prompt
    assert seed["temperament"] not in system_prompt


def test_self_context_config_defaults_and_example_are_disabled(monkeypatch):
    for key in [
        "CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED",
        "CONSCIOUSNESS_SELF_CONTEXT_MIN_INTERVAL",
        "CONSCIOUSNESS_SELF_CONTEXT_MAX_INTERVAL",
        "OPENROUTER_SELF_CONTEXT_MODEL",
        "CONSCIOUSNESS_SELF_CONTEXT_LLM_TIMEOUT",
    ]:
        monkeypatch.delenv(key, raising=False)

    import app.services.consciousness.config as config_module

    cfg = importlib.reload(config_module).ConsciousnessConfig()
    assert cfg.self_context_llm_enabled is False
    assert cfg.self_context_min_interval == 600
    assert cfg.self_context_max_interval == 10800
    assert cfg.self_context_model == "openai/gpt-4o-mini"
    assert cfg.self_context_llm_timeout_seconds == 20
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED=false" in example


@pytest.mark.asyncio
async def test_compose_updates_context_basis_and_timestamp():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state()
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    cfg = ConsciousnessConfig(
        self_context_llm_enabled=True,
        self_context_min_interval=600,
        self_context_max_interval=10800,
    )
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你现在在客厅画画，心情挺轻快，精力也还稳。",
    ) as llm:
        changed = await maybe_update_self_context(
            ws, nstate, cfg, trace_id="t-compose", now=now
        )

    assert changed is True
    assert ws.self_context == "你现在在客厅画画，心情挺轻快，精力也还稳。"
    assert ws.self_context_updated_at == now.isoformat()
    assert ws.self_context_basis == {
        "location": "living_room",
        "action": "画画",
        "mood_band": "好",
        "energy_status": "awake",
        "generated_at": now.isoformat(),
    }
    assert set(ws.self_context_basis) == {
        "location", "action", "mood_band", "energy_status", "generated_at"
    }
    llm.assert_called_once()


@pytest.mark.asyncio
async def test_gate_throttles_significant_changes_until_min_interval():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state(location="bedroom", action="读书")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    ws.self_context = "旧语境"
    ws.self_context_updated_at = (now - timedelta(seconds=300)).isoformat()
    ws.self_context_basis = {
        "location": "bedroom",
        "action": "读书",
        "mood_band": "好",
        "energy_status": "awake",
        "generated_at": ws.self_context_updated_at,
    }
    cfg = ConsciousnessConfig(
        self_context_llm_enabled=True,
        self_context_min_interval=600,
        self_context_max_interval=10800,
    )

    ws.location = "kitchen"
    with patch(
        "app.services.consciousness.self_context.chat_with_openrouter"
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg, now=now)

    assert changed is False
    assert ws.self_context == "旧语境"
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_gate_refreshes_after_min_interval_on_action_change():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state(action="画画")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    old_at = (now - timedelta(seconds=601)).isoformat()
    ws.self_context = "旧语境"
    ws.self_context_updated_at = old_at
    ws.self_context_basis = {
        "location": ws.location,
        "action": "读书",
        "mood_band": "好",
        "energy_status": "awake",
        "generated_at": old_at,
    }
    cfg = ConsciousnessConfig(self_context_llm_enabled=True)

    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你换成了画画，正安静地沉进去。",
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg, now=now)

    assert changed is True
    llm.assert_called_once()


@pytest.mark.asyncio
async def test_mood_change_is_throttled_by_min_interval():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state(action="读书")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    old_at = (now - timedelta(seconds=30)).isoformat()
    ws.self_context = "旧语境"
    ws.self_context_updated_at = old_at
    ws.self_context_basis = {
        "location": ws.location,
        "action": "读书",
        "mood_band": "低",
        "energy_status": "awake",
        "generated_at": old_at,
    }
    cfg = ConsciousnessConfig(
        self_context_llm_enabled=True,
        self_context_min_interval=600,
    )
    with patch(
        "app.services.consciousness.self_context.chat_with_openrouter"
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg, now=now)

    assert changed is False
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_max_interval_forces_refresh_without_significant_change():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state(action="读书")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    old_at = (now - timedelta(seconds=10801)).isoformat()
    ws.self_context = "旧语境"
    ws.self_context_updated_at = old_at
    ws.self_context_basis = {
        "location": ws.location,
        "action": "读书",
        "mood_band": "好",
        "energy_status": "awake",
        "generated_at": old_at,
    }
    cfg = ConsciousnessConfig(self_context_llm_enabled=True)
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你还在客厅读书，状态安稳。",
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg, now=now)

    assert changed is True
    llm.assert_called_once()


@pytest.mark.asyncio
async def test_sleep_wake_hard_trigger_bypasses_min_interval():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state(action="醒来")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    old_at = (now - timedelta(seconds=10)).isoformat()
    ws.self_context = "你刚才还睡着。"
    ws.self_context_updated_at = old_at
    ws.self_context_basis = {
        "location": ws.location,
        "action": "睡着",
        "mood_band": "好",
        "energy_status": "sleeping",
        "generated_at": old_at,
    }
    cfg = ConsciousnessConfig(
        self_context_llm_enabled=True,
        self_context_min_interval=600,
    )
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你刚醒来，意识还有点慢。",
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg, now=now)

    assert changed is True
    llm.assert_called_once()


@pytest.mark.asyncio
async def test_disabled_makes_zero_llm_calls():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state()
    cfg = ConsciousnessConfig(self_context_llm_enabled=False)
    with patch(
        "app.services.consciousness.self_context.chat_with_openrouter"
    ) as llm:
        changed = await maybe_update_self_context(ws, nstate, cfg)

    assert changed is False
    llm.assert_not_called()


def test_guard_rejects_unbacked_biographical_expansion():
    from app.services.consciousness.self_context import guard_self_context

    assert guard_self_context(
        "你最近经常画画，画起来很投入。",
        "事实1: 你最近经常画画。",
    )
    assert not guard_self_context(
        "你是设计专业学生，最近经常画画。",
        "事实1: 你最近经常画画。",
    )


def test_prompt_facts_keep_numbers_but_instruction_forbids_repeating_them():
    from app.services.consciousness import self_context as module

    ws, nstate = _state(action="画画")
    nstate.energy.value = 72
    nstate.mood.valence = -0.35

    prompt_facts, _ = module._build_facts(ws, nstate)

    assert "72" in prompt_facts
    assert "-0.35" in prompt_facts
    assert "你叫" not in prompt_facts
    assert "气质" not in prompt_facts
    assert "不得回写数字" in module._SYSTEM_PROMPT
    assert "不要复述姓名" in module._SYSTEM_PROMPT


def test_self_facts_feed_into_facts_and_count_as_input():
    # 自我库（阶段3）喂回：subject="neno" 自我事实进编号事实，且算合法输入（守门不误杀）
    from app.services.consciousness import self_context as module

    ws, nstate = _state(action="画画")
    facts = ["「画画」像是你常做、喜欢上手的事。"]
    prompt_facts, guard_facts = module._build_facts(ws, nstate, self_facts=facts)
    assert "「画画」像是你常做" in prompt_facts
    assert "「画画」像是你常做" in guard_facts  # 在 guard_facts 里 → 守门把它当输入，不拒


def test_self_facts_optional_keeps_old_behaviour():
    from app.services.consciousness import self_context as module

    ws, nstate = _state(action="画画")
    a, ga = module._build_facts(ws, nstate)
    b, gb = module._build_facts(ws, nstate, self_facts=None)
    assert a == b and ga == gb


@pytest.mark.asyncio
async def test_self_facts_passed_into_compose_prompt():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state()
    cfg = ConsciousnessConfig(self_context_llm_enabled=True)
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你在客厅画画，挺投入的。",
    ) as llm:
        await maybe_update_self_context(
            ws, nstate, cfg,
            self_facts=["「画画」像是你常做、喜欢上手的事。"],
        )
    user_msg = llm.call_args.kwargs["messages"][1]["content"]
    assert "「画画」像是你常做" in user_msg


@pytest.mark.asyncio
async def test_guard_rejection_keeps_old_context_and_basis():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state()
    old_basis = {
        "location": "bedroom",
        "action": "读书",
        "mood_band": "平",
        "energy_status": "awake",
        "generated_at": "2026-06-15T00:00:00+00:00",
    }
    ws.self_context = "旧语境"
    ws.self_context_basis = old_basis.copy()
    ws.self_context_updated_at = old_basis["generated_at"]
    cfg = ConsciousnessConfig(
        self_context_llm_enabled=True,
        self_context_min_interval=0,
    )
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="你是设计专业学生，正在客厅画画。",
    ), patch(
        "app.services.consciousness.self_context.log_event"
    ) as logged:
        changed = await maybe_update_self_context(ws, nstate, cfg)

    assert changed is False
    assert ws.self_context == "旧语境"
    assert ws.self_context_basis == old_basis
    assert ws.self_context_updated_at == old_basis["generated_at"]
    assert logged.call_args.args[1] == "self_context_guard_rejected"


@pytest.mark.asyncio
async def test_empty_or_failed_output_keeps_old_values():
    from app.services.consciousness.self_context import maybe_update_self_context

    ws, nstate = _state()
    ws.self_context = "旧语境"
    ws.self_context_basis = None
    ws.self_context_updated_at = ""
    cfg = ConsciousnessConfig(self_context_llm_enabled=True)
    with patch(
        "app.services.consciousness.self_context.OPENROUTER_API_KEY", "test-key"
    ), patch(
        "app.services.consciousness.self_context.chat_with_openrouter",
        return_value="",
    ), patch(
        "app.services.consciousness.self_context.log_event"
    ) as logged:
        changed = await maybe_update_self_context(ws, nstate, cfg)

    assert changed is False
    assert ws.self_context == "旧语境"
    assert ws.self_context_basis is None
    assert ws.self_context_updated_at == ""
    assert logged.call_args.args[1] == "self_context_warning"
