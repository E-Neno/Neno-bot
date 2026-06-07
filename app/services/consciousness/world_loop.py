from __future__ import annotations

import logging
import random
import time
from datetime import date, datetime, timedelta, timezone

from .action_validator import validate_ops
from .activity_episode_store import ActivityEpisodeStore
from .config import ConsciousnessConfig
from .daily_planner import DailyPlan, DailyPlanner
from .day_cycle import DayCycle
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .life_events import LifeEventSource
from .memory_recall import MemoryRecall
from .models import StateMutation
from .reflection_engine import ReflectionEngine
from .state_store import StateStore
from .world_brain import WorldBrain
from .world_drift import apply_drift
from .world_model import (
    apply_op, load_world_def, objects_in_room, WorldOp, WorldState,
)
from .world_pressure import PressureState, accumulate, is_hard, on_wake as pressure_on_wake, should_wake
from .world_store import WorldStore

_log = logging.getLogger(__name__)
_TZ8 = timezone(timedelta(hours=8))

ROOM_LABELS = {"bedroom": "卧室", "kitchen": "厨房", "living_room": "客厅", "balcony": "阳台"}
OBJ_EMOJI = {
    "bed": "🛏️", "desk": "🖊️", "bookshelf": "📚", "phone": "📱",
    "window_bed": "🪟", "lamp": "💡", "kettle": "🫖", "mug": "☕",
    "fridge": "🧊", "sofa": "🛋️", "book": "📖", "tv": "📺",
    "ceiling_light": "💡", "chair": "🪑", "plants": "🪴",
}
PHASE_ZH = {"morning": "上午", "afternoon": "下午", "evening": "傍晚", "night": "夜里"}
ENERGY_DROP_PER_TICK = 3.0
START_SIM_MINUTES = 7 * 60


def _obj_label(wd, state: WorldState, o: str) -> str:
    if o in state.dyn_objects:
        return state.dyn_objects[o].get("label", o)
    return wd.objects[o].label if o in wd.objects else o


def routine_decide(wd, state: WorldState):
    """LLM 关闭时的作息 mock；用 last action 防被漂移拖入重复。返回 (action, reason, ops, micro)。"""
    loc = state.location
    os_ = state.object_states
    last = state.recent_actions[-1]["action"] if state.recent_actions else ""
    if loc == "bedroom":
        if os_.get("bed") == "rumpled" and last != "整理床铺":
            return ("整理床铺", "起床先整理床", [WorldOp(op="set_state", object="bed", state="tidy")], "睡得还行")
        return ("去厨房", "想喝点热的", [WorldOp(op="move", to_room="kitchen")], "有点渴")
    if loc == "kitchen":
        if os_.get("kettle") != "boiling" and last != "烧水":
            return ("烧水", "水壶凉了烧点水", [WorldOp(op="set_state", object="kettle", state="boiling")], "等水开")
        return ("去客厅", "端着热水去客厅", [WorldOp(op="move", to_room="living_room")], None)
    if loc == "living_room":
        book = os_.get("book")
        if book == "closed" and last != "读完一章":
            return ("翻开书", "坐下读书", [WorldOp(op="set_state", object="book", state="reading")], "读得入神")
        if book == "reading":
            return ("读完一章", "读完这部分", [WorldOp(op="set_state", object="book", state="finished")], "有成就感")
        return ("去阳台", "读累了透透气", [
            WorldOp(op="set_state", object="book", state="closed"),
            WorldOp(op="move", to_room="balcony"),
        ], "伸了个懒腰")
    if loc == "balcony":
        if os_.get("plants") in {"needs_water", "wilting"}:
            return ("浇花", "盆栽该浇水了", [WorldOp(op="set_state", object="plants", state="fresh")], "叶子精神了")
        return ("回卧室", "站累了回房间", [
            WorldOp(op="move", to_room="bedroom"),
            WorldOp(op="set_state", object="bed", state="rumpled"),
        ], "想歇会儿")
    return ("发呆", "不知做什么", [], None)


def build_snapshot(wd, state: WorldState, nstate) -> dict:
    """从世界状态 + 内在状态构建控制台快照。无副作用。"""
    rooms_out = {}
    for room in wd.rooms:
        rooms_out[room] = {
            "label": ROOM_LABELS.get(room, room),
            "objects": [
                {"key": o, "label": _obj_label(wd, state, o),
                 "emoji": OBJ_EMOJI.get(o, "🆕" if o in state.dyn_objects else "▫️"),
                 "state": state.object_states.get(o, "?")}
                for o in objects_in_room(wd, state, room)
            ],
        }
    sim_minutes = state.sim_minutes or 0
    hh = (sim_minutes // 60) % 24
    mm = sim_minutes % 60
    plan = state.daily_plan or {}
    last = state.last_tick or {}
    snap = {
        "sim_time": f"{hh:02d}:{mm:02d}",
        "location": state.location,
        "rooms": rooms_out,
        "money": state.money,
        "plan": plan.get("items", []),
        "carried_over": plan.get("carried_over", []),
        "recent": state.recent_actions[-6:],
        "gone": [g.get("label") or g.get("object", "") for g in state.gone_log[-5:]],
        "last": last,
    }
    if nstate is not None:
        try:
            snap["energy"] = round(float(nstate.energy.value), 0)
            snap["energy_status"] = nstate.energy.status
            snap["mood"] = nstate.mood.label
            snap["mood_valence"] = round(float(nstate.mood.valence), 2)
        except AttributeError:
            pass
    return snap


class WorldLoop:
    """常驻世界循环（单一可信源）。app 注册定时 tick；debug 端点手动步进；demo 复用。"""

    def __init__(
        self,
        state_store: StateStore,
        config: ConsciousnessConfig,
        *,
        recall: MemoryRecall | None = None,
        world_store: WorldStore | None = None,
    ) -> None:
        self._config = config
        self._state_store = state_store
        self._wd = load_world_def()
        self._world_store = world_store or WorldStore(self._wd)
        self._brain = WorldBrain(self._wd, config)
        self._planner = DailyPlanner(self._wd, config)
        self._day_cycle = DayCycle(config)
        self._recorder = ExperienceRecorder()
        self._recall = recall or MemoryRecall(db=None, config=config)
        self._episode_store = ActivityEpisodeStore()
        self._reflection = ReflectionEngine(
            state_store, self._recorder, self._recall, config, self._episode_store
        )
        self._events = LifeEventSource(config)
        self._rng = random.Random()
        self._prev_action = ""
        self._day_no = 1

    def register_jobs(self, scheduler) -> bool:
        """world_loop_enabled 为真才注册定时 tick。返回是否注册。"""
        if not self._config.world_loop_enabled:
            _log.info("world loop disabled; not registering tick job")
            return False
        scheduler.add_job(
            self.tick,
            "interval",
            seconds=self._config.world_loop_interval_seconds,
            id="world_loop_tick",
            replace_existing=True,
        )
        _log.info("world loop registered (interval=%ss)", self._config.world_loop_interval_seconds)
        return True

    async def tick(self) -> dict:
        """一次融合 tick。推进世界 + 内在状态，写库，返回快照。"""
        cfg = self._config
        wd = self._wd
        step = cfg.world_sim_minutes_per_tick

        ws = await self._world_store.read()
        if not ws.daily_plan:
            plan = await self._planner.make_plan(date="day1", residue="", carried_over=[])
            ws.daily_plan = plan.model_dump()
            await self._world_store.write(ws)

        # ── 时钟：从真实时间(UTC+8)推导，不再累加 ──
        now8 = datetime.now(_TZ8)
        sim_minutes = now8.hour * 60 + now8.minute
        hour = now8.hour
        phase = self._day_cycle.phase_of(hour)
        nstate = await self._state_store.read()

        transition = self._day_cycle.check_sleep_wake(nstate, phase, hour)
        sleeping = False
        action = reason = ""
        micro = None
        drift = []
        event = None
        event_mood = 0.0

        if transition == "fall_asleep":
            await self._day_cycle.on_sleep(self._state_store)
            nstate = await self._state_store.read()
            sleeping = True
            action, reason = "睡觉", "困了，回房间睡下"
        elif transition == "wake_up":
            self._day_no += 1
            real_day = datetime.now(_TZ8).date()
            await self._day_cycle.on_wake(
                self._state_store, self._reflection, self._world_store, self._planner,
                today=f"day{self._day_no}", yesterday=real_day,
            )
            nstate = await self._state_store.read()
            action, reason = "醒来", "睡醒了，看看今天的计划"
        elif nstate.energy.status == "sleeping":
            sleeping = True
            action, reason = "睡着", "还在睡"

        ws = await self._world_store.read()

        if not sleeping and action == "":
            drifted, drift = apply_drift(wd, ws, elapsed_minutes=step, config=cfg)
            event = self._events.maybe_emit(
                world_def=wd, world_state=drifted, nstate=nstate, phase=phase, rng=self._rng
            )
            if event is not None:
                if event.world_op is not None:
                    acc, _ = validate_ops(wd, drifted, [event.world_op])
                    if acc:
                        drifted = apply_op(wd, drifted, event.world_op)
                event_mood = event.mood_delta

            # ── 压力门控：从 ws 重建 PressureState ──
            pressure = PressureState(
                value=ws.pressure_value,
                last_wake_ts=ws.pressure_last_wake_ts,
                wakes_this_hour=ws.pressure_wakes_this_hour,
                hour_anchor=ws.pressure_hour_anchor,
            )

            # 收集本 tick 事件种类
            event_kinds: list[str] = []
            if event is not None:
                event_kinds.append(event.kind if hasattr(event, "kind") else "action_done")
            if drift:
                event_kinds.append("plant_thirsty")
            if ws.last_tick and ws.last_tick.get("phase") != PHASE_ZH.get(phase):
                event_kinds.append("phase_change")
            if drifted.money < 30:
                event_kinds.append("money_low")

            now_real = time.time()
            hard = is_hard(event_kinds, cfg)
            pressure = accumulate(pressure, event_kinds, cfg, now=now_real)
            wake, wake_reason = should_wake(pressure, cfg, now=now_real, hard_event=hard)

            if wake and cfg.world_llm_enabled:
                # LLM 路径（真想）
                plan_dp = DailyPlan.model_validate(ws.daily_plan) if ws.daily_plan else None
                q = [drifted.location]
                if plan_dp:
                    q += [it.intent for it in plan_dp.items if it.phase == phase]
                memories = await self._recall.recall_weighted(
                    " ".join(q), now=datetime.now(timezone.utc)
                )
                recent_ctx = [
                    {"action": r.get("action", ""), "ago_min": r.get("ago_min", "?")}
                    for r in drifted.recent_actions[-6:]
                ]
                plan_obj = await self._brain.decide(
                    drifted, nstate=nstate, phase=phase, plan=plan_dp,
                    memories=memories, recent=recent_ctx, event=event,
                )
                action, reason, micro, ops = (
                    plan_obj.action, plan_obj.reasoning, plan_obj.micro_event, plan_obj.world_ops,
                )
                pressure = pressure_on_wake(pressure, now=now_real)
            else:
                # 免费 mock 路径（滑行）
                action, reason, ops, micro = routine_decide(wd, drifted)

            sim = drifted
            op_log = []
            for op in ops:
                acc, rej = validate_ops(wd, sim, [op])
                if acc:
                    sim = apply_op(wd, sim, op)
                    op_log.append({"r": "accept", "t": op.object or op.to_room, "s": op.state})
                else:
                    op_log.append({"r": "reject", "t": op.object or op.to_room, "s": rej[0][1]})

            sim.recent_actions = (sim.recent_actions + [{"action": action, "ago_min": 0}])[-8:]
            for r in sim.recent_actions[:-1]:
                r["ago_min"] = r.get("ago_min", 0) + step
            sim.sim_minutes = sim_minutes
            # 持久化压力状态
            sim.pressure_value = pressure.value
            sim.pressure_last_wake_ts = pressure.last_wake_ts
            sim.pressure_wakes_this_hour = pressure.wakes_this_hour
            sim.pressure_hour_anchor = pressure.hour_anchor
            if sim.daily_plan:
                for it in sim.daily_plan.get("items", []):
                    if it["phase"] == phase and not it.get("done"):
                        if any(w and w in (action + reason) for w in [it["intent"][:2]]):
                            it["done"] = True
            sim.last_tick = {
                "action": action, "reasoning": reason, "drift": drift,
                "ops": op_log, "micro": micro,
                "event": (event.content if event is not None else None),
                "sleeping": False, "phase": PHASE_ZH.get(phase, phase),
                "real_time": now8.strftime("%H:%M"),
                "wake": wake, "wake_reason": wake_reason, "pressure": round(pressure.value, 1),
            }
            await self._world_store.write(sim)
            ws = sim

            await self._recorder.record(InnerExperienceIn(
                trace_id="life_world", source="life_simulation", kind="micro_event",
                content=(micro or action), salience=0.45,
                metadata={"place": sim.location, "time_phase": phase},
            ))
            if action != self._prev_action and action not in {"去厨房", "去客厅", "去阳台", "回卧室"}:
                try:
                    await self._episode_store.start_episode(
                        activity_key=action, activity_label=action,
                        place=sim.location, time_phase=phase, reason=reason,
                    )
                except Exception:  # noqa: BLE001
                    pass
            self._prev_action = action

            energy = nstate.energy.model_copy(deep=True)
            energy.value = max(0.0, energy.value - ENERGY_DROP_PER_TICK)
            await self._state_store.submit_mutation(StateMutation(
                energy=energy, mood_valence_delta=0.01 + event_mood, reason="world loop tick"))
            nstate = await self._state_store.read()
        else:
            ws.sim_minutes = sim_minutes
            ws.last_tick = {
                "action": action, "reasoning": reason, "drift": [], "ops": [],
                "micro": micro, "event": None, "sleeping": sleeping,
                "phase": PHASE_ZH.get(phase, phase),
                "real_time": now8.strftime("%H:%M"),
            }
            await self._world_store.write(ws)

        ws.sim_minutes = sim_minutes  # 写回真实时间，不再累加
        await self._world_store.write(ws)
        return build_snapshot(wd, ws, nstate)
