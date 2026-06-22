"""意图通道（刀① capstone）：用户的话 → 意图候选 → 世界 LLM 临场决定做不做（无常）。

架构：聊天侧不写 WorldState（避免和 world_loop 读改写抢）；world_loop 读 cursor 之后的
新用户消息经历，当意图候选喂给世界 LLM，喂过推进 cursor。她可做可不做——LLM 在回路里判断，不堆规则表。
"""
import pytest

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_brain import WorldBrain
from app.services.consciousness.world_model import (
    load_world_def, seed_world_state, WorldState,
)


def _brain():
    wd = load_world_def()
    return WorldBrain(wd, ConsciousnessConfig()), seed_world_state(wd)


def test_wishes_surface_with_impermanence_framing():
    brain, ws = _brain()
    msg = brain._build_user_message(ws, wishes=["有人找我，说了「帮我把杯子放厨房」"])
    assert "帮我把杯子放厨房" in msg
    # 无常框架：明示「也许想让你做」「你可以不」——不是命令
    assert "也许" in msg and "可以不" in msg


def test_no_wishes_no_block():
    brain, ws = _brain()
    msg = brain._build_user_message(ws, wishes=None)
    assert "对方最近说的" not in msg
    msg2 = brain._build_user_message(ws, wishes=[])
    assert "对方最近说的" not in msg2


def test_wishes_capped_to_three():
    brain, ws = _brain()
    wishes = [f"想法{i}" for i in range(6)]
    msg = brain._build_user_message(ws, wishes=wishes)
    # 只带最近 3 条，避免堆积刷屏
    assert "想法5" in msg and "想法3" in msg
    assert "想法2" not in msg


def test_intent_cursor_defaults_empty_on_old_state():
    st = WorldState.model_validate({"location": "bedroom", "object_states": {}})
    assert st.intent_cursor == ""


@pytest.mark.asyncio
async def test_mock_path_ignores_wishes_unchanged():
    # 世界 LLM 关 → 走确定性 mock，wishes 不改变行为（守 NENO 硬规则）
    wd = load_world_def()
    brain = WorldBrain(wd, ConsciousnessConfig(world_llm_enabled=False))
    ws = seed_world_state(wd)
    ws.location = "kitchen"
    plan_a = await brain.decide(ws, wishes=["有人找我，说了「去阳台」"])
    plan_b = await brain.decide(ws)
    assert plan_a.action == plan_b.action
    assert [o.op for o in plan_a.world_ops] == [o.op for o in plan_b.world_ops]
