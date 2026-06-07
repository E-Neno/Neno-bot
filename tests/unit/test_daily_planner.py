import asyncio
from unittest.mock import patch

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import load_world_def
from app.services.consciousness.daily_planner import DailyPlanner, DailyPlan


def _planner(enabled: bool):
    wd = load_world_def()
    cfg = ConsciousnessConfig(world_planner_enabled=enabled)
    return DailyPlanner(wd, cfg)


def test_disabled_returns_mock_plan_with_three_phases():
    p = _planner(False)
    with patch("app.services.consciousness.daily_planner.chat_with_openrouter") as m:
        plan = asyncio.run(p.make_plan(date="2026-06-07", residue="", carried_over=[]))
    m.assert_not_called()
    phases = {item.phase for item in plan.items}
    assert phases == {"morning", "afternoon", "evening"}


def test_disabled_carries_over_unfinished():
    p = _planner(False)
    plan = asyncio.run(
        p.make_plan(date="2026-06-07", residue="", carried_over=["昨天那本书没读完"])
    )
    assert "昨天那本书没读完" in plan.carried_over


def test_enabled_parses_llm_json():
    p = _planner(True)
    fake = (
        '{"items":['
        '{"phase":"morning","intent":"把那本书读完"},'
        '{"phase":"afternoon","intent":"收拾书桌"},'
        '{"phase":"evening","intent":"早点休息"}]}'
    )
    with patch(
        "app.services.consciousness.daily_planner.chat_with_openrouter",
        return_value=fake,
    ), patch("app.services.consciousness.daily_planner.OPENROUTER_API_KEY", "k"):
        plan = asyncio.run(p.make_plan(date="2026-06-07", residue="书没读完", carried_over=[]))
    intents = [i.intent for i in plan.items]
    assert "把那本书读完" in intents
    assert len(plan.items) == 3


def test_enabled_garbage_falls_back_to_mock():
    p = _planner(True)
    with patch(
        "app.services.consciousness.daily_planner.chat_with_openrouter",
        return_value="对不起我不会",
    ), patch("app.services.consciousness.daily_planner.OPENROUTER_API_KEY", "k"):
        plan = asyncio.run(p.make_plan(date="2026-06-07", residue="", carried_over=["x"]))
    assert isinstance(plan, DailyPlan)
    assert {i.phase for i in plan.items} == {"morning", "afternoon", "evening"}
    assert "x" in plan.carried_over  # 降级也保留未完成


def test_enabled_network_error_falls_back():
    p = _planner(True)
    with patch(
        "app.services.consciousness.daily_planner.chat_with_openrouter",
        side_effect=RuntimeError("boom"),
    ), patch("app.services.consciousness.daily_planner.OPENROUTER_API_KEY", "k"):
        plan = asyncio.run(p.make_plan(date="2026-06-07", residue="", carried_over=[]))
    assert len(plan.items) == 3
