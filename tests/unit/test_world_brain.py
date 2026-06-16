import asyncio
from unittest.mock import patch

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import load_world_def, seed_world_state
from app.services.consciousness.world_brain import WorldBrain, _parse_plan


def _brain(llm_enabled: bool):
    wd = load_world_def()
    cfg = ConsciousnessConfig(world_llm_enabled=llm_enabled)
    return wd, WorldBrain(wd, cfg)


def test_llm_disabled_uses_mock_no_network():
    wd, brain = _brain(False)
    st = seed_world_state(wd)
    st.location = "kitchen"
    # 若意外发起网络调用，patch 会让它抛错；这里断言根本不会调用
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter"
    ) as mock_call:
        plan = asyncio.run(brain.decide(st))
    mock_call.assert_not_called()
    assert plan.action == "boil_water"


def test_llm_enabled_parses_json_response():
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "kitchen"
    fake = (
        '{"action":"make_tea","reasoning":"想喝茶",'
        '"world_ops":[{"op":"set_state","object":"kettle","state":"boiling"}],'
        '"micro_event":"等水开"}'
    )
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value=fake,
    ), patch("app.services.consciousness.world_brain.OPENROUTER_API_KEY", "test-key"):
        plan = asyncio.run(brain.decide(st))
    assert plan.action == "make_tea"
    assert plan.world_ops[0].object == "kettle"
    assert plan.world_ops[0].state == "boiling"


def test_llm_enabled_handles_code_fence():
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    fake = '```json\n{"action":"rest","reasoning":"累了","world_ops":[],"micro_event":null}\n```'
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value=fake,
    ), patch("app.services.consciousness.world_brain.OPENROUTER_API_KEY", "test-key"):
        plan = asyncio.run(brain.decide(st))
    assert plan.action == "rest"
    assert plan.world_ops == []


def test_llm_garbage_output_falls_back_to_mock():
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "kitchen"
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value="抱歉我不知道",
    ), patch("app.services.consciousness.world_brain.OPENROUTER_API_KEY", "test-key"):
        plan = asyncio.run(brain.decide(st))
    assert plan.action == "boil_water"  # 降级到 mock


def test_llm_network_error_falls_back_to_mock():
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "kitchen"
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        side_effect=RuntimeError("LLM request failed"),
    ), patch("app.services.consciousness.world_brain.OPENROUTER_API_KEY", "test-key"):
        plan = asyncio.run(brain.decide(st))
    assert plan.action == "boil_water"  # 降级到 mock


def test_parse_plan_extracts_embedded_json():
    plan = _parse_plan('好的：{"action":"x","reasoning":"y","world_ops":[]} 完成')
    assert plan is not None
    assert plan.action == "x"


def test_prompt_includes_state_memory_plan_recent():
    from app.services.consciousness.models import NenoState
    from app.services.consciousness.daily_planner import DailyPlan, DayPlanItem

    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "living_room"
    nstate = NenoState()
    nstate.energy.value = 40
    nstate.mood.label = "疲惫"
    plan = DailyPlan(date="2026-06-07", items=[DayPlanItem(phase="afternoon", intent="把书读完")])
    memories = [{"content": "昨天读了一半的书"}]
    recent = [{"action": "倒水", "ago_min": 10}]
    fake = '{"action":"rest","reasoning":"累了","world_ops":[],"micro_event":null}'

    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value=fake,
    ) as mock_call, patch(
        "app.services.consciousness.world_brain.OPENROUTER_API_KEY", "k"
    ):
        asyncio.run(brain.decide(
            st, nstate=nstate, phase="afternoon", plan=plan,
            memories=memories, recent=recent,
        ))
    user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
    assert "把书读完" in user_msg        # 计划进了 prompt
    assert "昨天读了一半的书" in user_msg  # 记忆进了 prompt
    assert "倒水" in user_msg            # 最近行动进了 prompt（防绕圈）
    assert "40" in user_msg             # 精力进了 prompt
    assert "afternoon" in user_msg       # 时段进了 prompt


def test_prompt_always_includes_seed_and_optional_self_context():
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    without_context = brain._build_user_message(st)
    assert "18" in without_context
    assert "活泼" in without_context

    st.self_context = "你现在窝在客厅画画，心情很松。"
    with_context = brain._build_user_message(st)
    assert "你现在窝在客厅画画，心情很松。" in with_context


def test_decide_backward_compatible_without_context():
    # 不传新参数仍可工作（竖切1/3 兼容）
    wd, brain = _brain(False)
    st = seed_world_state(wd)
    st.location = "kitchen"
    plan = asyncio.run(brain.decide(st))
    assert plan.action == "boil_water"


def test_prompt_includes_event_money_gone(monkeypatch=None):
    from app.services.consciousness.life_events import LifeEvent
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "kitchen"
    st.money = 77
    st.gone_log = [{"object": "mug", "label": "旧马克杯", "cause": "摔碎", "when": "x"}]
    event = LifeEvent(kind="message", content="手机震了一下，有条新消息", mood_delta=0.05)
    fake = '{"action":"rest","reasoning":"r","world_ops":[],"micro_event":null}'
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value=fake,
    ) as mock_call, patch(
        "app.services.consciousness.world_brain.OPENROUTER_API_KEY", "k"
    ):
        asyncio.run(brain.decide(st, event=event))
    user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
    assert "手机震了一下" in user_msg     # 刚发生的事件
    assert "77" in user_msg              # 钱包
    assert "旧马克杯" in user_msg          # 失去过的东西


def test_prompt_lists_dynamic_object_in_room():
    from app.services.consciousness.world_model import apply_op, WorldOp
    wd, brain = _brain(True)
    st = seed_world_state(wd)
    st.location = "balcony"
    st = apply_op(wd, st, WorldOp(op="create_object", object="tulips",
                                  category="plant", room="balcony", label="郁金香", cost=10))
    fake = '{"action":"x","reasoning":"r","world_ops":[]}'
    with patch(
        "app.services.consciousness.world_brain.chat_with_openrouter",
        return_value=fake,
    ) as mock_call, patch(
        "app.services.consciousness.world_brain.OPENROUTER_API_KEY", "k"
    ):
        asyncio.run(brain.decide(st))
    user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
    assert "tulips" in user_msg   # 买来的动态物品出现在房间清单里
