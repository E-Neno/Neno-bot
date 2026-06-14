from __future__ import annotations

from pydantic import BaseModel

from .config import ConsciousnessConfig
from .world_model import WorldDef, WorldOp, WorldState, is_outside

EMIT_PROB = 0.30      # 普通事件触发概率（每 tick）
MISHAP_PROB = 0.08    # 小意外（打碎东西）概率，更低

# 刀③：在外面各场所带回来的一句见闻（喂回经历流；非脚本动作，只是她注意到的东西）
_OUTING_FLAVOR: dict[str, str] = {
    "building_entrance": "站在小区楼下，几个邻居拎着东西进进出出",
    "convenience_store": "便利店灯很亮，关东煮的热气和饭团排在一起",
    "cafe":              "咖啡馆里有磨豆子的声音，靠窗的人各自安静着",
    "park":              "小公园里风把树叶吹得沙沙响，有人在遛狗",
}


class LifeEvent(BaseModel):
    kind: str                 # weather/message/craving/memory/mishap/chore/small_joy/idle_thought/outing
    content: str
    mood_delta: float = 0.0   # -0.3 ~ +0.3
    world_op: WorldOp | None = None


class LifeEventSource:
    """从世界/状态/时段派生的低频生活事件（非纯随机文案）。

    rng 由调用方传入（random.Random），保证可重放、可测；全天频率受 EMIT_PROB 限制。
    """

    def __init__(self, config: ConsciousnessConfig) -> None:
        self._config = config

    def maybe_emit(self, *, world_def: WorldDef, world_state: WorldState,
                   nstate, phase: str, rng) -> LifeEvent | None:
        p = rng.random()

        # 1) 小意外：当前房间有未碎的饮具时，低概率打碎
        if p < MISHAP_PROB:
            target = self._unbroken_drinkware(world_def, world_state)
            if target is not None:
                return LifeEvent(
                    kind="mishap",
                    content=f"手一滑，{world_def.objects[target].label}磕了一下",
                    mood_delta=-0.15,
                    world_op=WorldOp(op="set_state", object=target, state="broken",
                                     reason="手滑"),
                )

        # 2) 普通事件（低频）
        if p >= EMIT_PROB:
            return None

        # 优先级派生：失去过的东西 > 早晨天气 > 低能量渴望 > 场景小事 > 默认消息
        if world_state.gone_log:
            last = world_state.gone_log[-1]
            label = last.get("label") or last.get("object", "那个东西")
            return LifeEvent(
                kind="memory",
                content=f"忽然想起扔掉的{label}，心里空落落的",
                mood_delta=-0.10,
            )
        if phase == "morning":
            return LifeEvent(
                kind="weather",
                content="窗外开始下小雨，屋里暗了一些",
                mood_delta=-0.05,
                world_op=WorldOp(op="set_state", object="window_bed", state="dim",
                                 reason="下雨"),
            )
        if getattr(nstate.energy, "value", 100) < 40:
            return LifeEvent(
                kind="craving",
                content="突然很想喝点甜的",
                mood_delta=0.0,
            )
        # 刀③：在外面 → 带回一句见闻，喂回经历流（在外面优先于家里的走神/小事）
        if is_outside(world_def, world_state.location):
            return LifeEvent(
                kind="outing",
                content=_OUTING_FLAVOR.get(world_state.location, "在外面走了走，街上的声音和家里不一样"),
                mood_delta=0.05,
            )
        if (
            world_state.location == "kitchen"
            and world_state.object_states.get("dish_towel") == "needs_wash"
        ):
            return LifeEvent(
                kind="chore",
                content="看见擦手巾该洗了，顺手记下这件小家务",
                mood_delta=-0.02,
            )
        if (
            world_state.location == "balcony"
            and world_state.object_states.get("plants") == "fresh"
        ):
            return LifeEvent(
                kind="small_joy",
                content="盆栽刚好精神，叶子在光里显得很亮",
                mood_delta=0.08,
            )
        if phase == "evening":
            return LifeEvent(
                kind="idle_thought",
                content="夜里安静下来，思绪不知不觉飘远了一会儿",
                mood_delta=0.01,
            )
        return LifeEvent(
            kind="message",
            content="手机震了一下，有条新消息",
            mood_delta=0.05,
            world_op=WorldOp(op="set_state", object="phone", state="has_unread",
                             reason="来消息"),
        )

    @staticmethod
    def _unbroken_drinkware(world_def: WorldDef, world_state: WorldState) -> str | None:
        room = world_state.location
        for o in world_def.rooms.get(room, {}).get("objects", []):
            if o not in world_def.objects:
                continue
            if world_def.objects[o].category != "drinkware":
                continue
            if world_state.object_states.get(o) != "broken":
                return o
        return None
