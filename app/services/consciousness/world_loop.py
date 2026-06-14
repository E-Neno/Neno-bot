from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import date, datetime, timedelta, timezone

from app.config import WORLD_PRESENCE_GATE_ENABLED, WORLD_PRESENCE_WX_AUTO_SEND

from .action_validator import validate_ops
from .activity_episode_store import ActivityEpisodeStore
from .config import ConsciousnessConfig
from .daily_planner import DailyPlan, DailyPlanner
from .day_cycle import DayCycle
from .energy_dynamics import step_energy
from .presence import DEFER_COOLDOWN_SECONDS, mark_message_experience_expressed
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .life_events import LifeEventSource
from .memory_recall import MemoryRecall
from .models import StateMutation
from .reflection_engine import ReflectionEngine
from .state_store import StateStore
from .world_brain import WorldBrain
from .world_drift import apply_drift
from .world_model import (
    _label_of, apply_op, find_goal_thread, find_thread, is_outside, load_world_def, make_thread,
    obj_category, objects_in_room, reconcile_owe_reply_thread, WorldOp, WorldState,
)
from .world_pressure import PressureState, accumulate, is_hard, on_wake as pressure_on_wake, should_wake
from .world_store import WorldStore

_log = logging.getLogger(__name__)
_TZ8 = timezone(timedelta(hours=8))

ROOM_LABELS = {
    "bedroom": "卧室", "kitchen": "厨房", "living_room": "客厅", "balcony": "阳台",
    # 刀③ 开放世界：玄关（门槛）+ 外部场所
    "entryway": "玄关", "building_entrance": "小区楼下",
    "convenience_store": "便利店", "cafe": "咖啡馆", "park": "小公园",
}
OBJ_EMOJI = {
    "bed": "🛏️", "desk": "🖊️", "bookshelf": "📚", "phone": "📱",
    "window_bed": "🪟", "lamp": "💡", "kettle": "🫖", "mug": "☕",
    "fridge": "🧊", "sofa": "🛋️", "book": "📖", "tv": "📺",
    "ceiling_light": "💡", "chair": "🪑", "plants": "🪴",
    # 刀② 世界深度新增物品
    "journal": "📔", "headphones": "🎧", "laundry": "🧺", "tea_tin": "🍵",
    "cutting_board": "🔪", "dish_towel": "🧻", "record_player": "💿",
    "floor_cushion": "🟫", "sketchbook": "🎨", "watering_can": "🪣",
    "drying_rack": "🪜", "wind_chime": "🎐",
    # 刀③ 外部场所物品
    "shoe_rack": "👟", "door_keys": "🔑", "mailbox": "📮", "parcel_locker": "📦",
    "snack_shelf": "🍫", "register": "🛒", "cafe_counter": "☕",
    "window_seat": "🪑", "coffee_cup": "🥤", "park_bench": "🪑",
    "old_tree": "🌳", "street_lamp": "🏮",
    # 世界扩容：家内房间
    "wardrobe": "👗", "bedside_table": "🗄️", "alarm_clock": "⏰", "mirror": "🪞",
    "blanket": "🛌", "pillow": "🛏️", "storage_box": "📦", "photo_frame": "🖼️",
    "curtain": "🪟", "stove": "🔥", "rice_cooker": "🍚", "frying_pan": "🍳",
    "saucepan": "🥘", "knife_set": "🔪", "bowl": "🥣", "plate": "🍽️",
    "chopsticks": "🥢", "spice_rack": "🧂", "oil_bottle": "🫗", "sink": "🚰",
    "trash_bin": "🗑️", "coffee_table": "🫖", "side_table": "🪑", "rug": "🟫",
    "curtains_living": "🪟", "remote_control": "🎛️", "speaker": "🔊",
    "game_console": "🎮", "magazine_rack": "📰", "wall_clock": "🕰️",
    "vase": "🏺", "reading_lamp": "💡", "flower_pot": "🌷", "herb_planter": "🌿",
    "succulent": "🌵", "garden_shears": "✂️", "plant_stand": "🪴",
    "outdoor_table": "🪑", "storage_cabinet": "🗄️", "broom": "🧹",
    "dustpan": "🧹", "clothespin_basket": "🧺", "balcony_light": "💡",
    "rain_gauge": "🌧️", "bird_feeder": "🌾",
    # 世界扩容：玄关与外部场所
    "coat_rack": "🧥", "umbrella_stand": "🌂", "doormat": "🟫",
    "entry_mirror": "🪞", "intercom": "📟", "reusable_bag": "🛍️",
    "notice_board": "📌", "elevator": "🛗", "stairwell_light": "💡",
    "security_camera": "📹", "lobby_bench": "🪑", "recycling_bins": "♻️",
    "drink_cooler": "🥤", "instant_noodle_shelf": "🍜", "fruit_basket": "🍎",
    "freezer_case": "🧊", "shopping_basket": "🛒", "receipt_printer": "🧾",
    "espresso_machine": "☕", "pastry_case": "🥐", "menu_board": "📋",
    "cafe_table": "🪑", "sugar_jar": "🫙", "walking_path": "🚶",
    "flower_bed": "🌼", "playground": "🛝", "drinking_fountain": "🚰",
    "park_trash_can": "🗑️",
}
PHASE_ZH = {"morning": "上午", "afternoon": "下午", "evening": "傍晚", "night": "夜里"}
START_SIM_MINUTES = 7 * 60

# 瞬态动作集合：滑行接续时不应延续的动作（移动/睡眠类）
_TRANSIENT_ACTIONS = {"睡觉", "睡着", "醒来", "去厨房", "去客厅", "去阳台", "回卧室"}


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
                 "state": state.object_states.get(o, "?"),
                 "category": obj_category(wd, state, o) or ""}
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
        "threads": [
            {"kind": t["kind"], "topic": t["topic"],
             "intensity": round(t["intensity"], 2), "carry": t.get("carry_count", 0),
             "mood": t.get("mood", ""), "resolved": t.get("resolved", False)}
            for t in (state.open_threads or [])
        ],
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
        self._consuming = False  # 防重入：pending 捡取期间不重复捡（杜绝双发）

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

        # ── 精力前置结算：按真实经过时间积分（上一拍动作 + 心情 + 昼夜调制）──
        # submit 只管持久化（异步落库）；判睡醒与下游分支一律用就地结算后的内存值，
        # 避免依赖「submit→read 立刻可见」（队列在 tick 内不让出事件循环，读不到刚提交的值）。
        now_real = time.time()
        prev_act = (ws.last_tick or {}).get("action", "")
        settled = step_energy(
            nstate.energy, status=nstate.energy.status, action=prev_act,
            valence=nstate.mood.valence, hour8=hour, now=now_real,
            time_scale=cfg.world_time_scale,
        )
        nstate.energy = settled
        await self._state_store.submit_mutation(
            StateMutation(energy=settled, reason="energy wallclock step")
        )

        transition = self._day_cycle.check_sleep_wake(nstate)
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

            # 牵挂压力注入：仅 LLM 路径，不影响 mock 模式的 pressure 数值
            if cfg.world_llm_enabled:
                _active = [
                    t for t in (ws.open_threads or [])
                    if not t.get("resolved") and (
                        t["kind"] in ("loss", "residue") or
                        (t["kind"] == "goal" and t.get("carry_count", 0) >= 2)
                    )
                ]
                if _active:
                    event_kinds.append("open_thread")
                    if max(t.get("intensity", 0) for t in _active) >= 0.7:
                        event_kinds.append("open_thread")

            now_real = time.time()
            hard = is_hard(event_kinds, cfg)
            pressure = accumulate(pressure, event_kinds, cfg, now=now_real)
            wake, wake_reason = should_wake(pressure, cfg, now=now_real, hard_event=hard)

            if wake and cfg.world_llm_enabled:
                # ── 真想：LLM 路径 ──
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
                # 活跃牵挂传给 brain（loss/residue 任意强度，goal 需 carry>=2）
                active_threads = [
                    t for t in (ws.open_threads or [])
                    if not t.get("resolved") and (
                        t["kind"] in ("loss", "residue") or
                        (t["kind"] == "goal" and t.get("carry_count", 0) >= 2)
                    )
                ]
                # 活泼度信号：在一个屋待久了/今天没出门 → 给她"有点闷"的感觉（决定仍由她做）
                _today = now8.date().isoformat()
                _restless = []
                if (ws.room_streak or 0) >= 6:
                    _restless.append(f"你在{ROOM_LABELS.get(drifted.location, drifted.location)}已经待了好一会儿了")
                if ws.last_outing_day != _today and 8 <= now8.hour <= 21:
                    _restless.append("今天还没出过门")
                plan_obj = await self._brain.decide(
                    drifted, nstate=nstate, phase=phase, plan=plan_dp,
                    memories=memories, recent=recent_ctx, event=event,
                    threads=active_threads, restless="；".join(_restless),
                )
                action, reason, micro, ops = (
                    plan_obj.action, plan_obj.reasoning, plan_obj.micro_event, plan_obj.world_ops,
                )
                pressure = pressure_on_wake(pressure, now=now_real)
            elif cfg.world_llm_enabled:
                # ── 滑行接续：LLM 开着但这拍没醒 → 继续上一次真想定的事 ──
                last_action = (ws.last_tick or {}).get("action")
                if last_action and last_action not in _TRANSIENT_ACTIONS:
                    action = last_action
                    reason = "继续手上的事"
                    ops = []
                    micro = None
                else:
                    action, reason, ops, micro = routine_decide(wd, drifted)
            else:
                # ── 纯 mock 模式（LLM 关）：保持现状，每拍 routine_decide ──
                action, reason, ops, micro = routine_decide(wd, drifted)

            sim = drifted
            op_log = []
            today_str = now8.date().isoformat()
            for op in ops:
                acc, rej = validate_ops(wd, sim, [op])
                if acc:
                    # loss 牵挂诞生：destroy_object 被接受后派生
                    if op.op == "destroy_object":
                        label = _label_of(wd, sim, op.object)
                        tid = f"loss:扔掉的{label}"
                        threads_mut = list(sim.open_threads or [])
                        existing = find_thread(threads_mut, tid)
                        if existing:
                            existing["intensity"] = 0.6  # 重新被勾起
                            existing["last_touch_day"] = today_str
                        else:
                            threads_mut.append(make_thread(
                                "loss", f"扔掉的{label}",
                                day=today_str, intensity=0.6, mood="空落落",
                            ))
                        sim.open_threads = threads_mut
                    sim = apply_op(wd, sim, op)
                    op_log.append({"r": "accept", "t": op.object or op.to_room, "s": op.state})
                else:
                    op_log.append({"r": "reject", "t": op.object or op.to_room, "s": rej[0][1]})

            # 先让已有条目「变久」，再决定是否记新动作
            for r in sim.recent_actions:
                r["ago_min"] = r.get("ago_min", 0) + step
            # 滑行接续在重复同一个动作时不重复记账，否则长卷会显示「连开 6 次灯」
            # （glide 只是继续手上的事，不是又做了一遍）
            if not sim.recent_actions or sim.recent_actions[-1].get("action") != action:
                sim.recent_actions = (sim.recent_actions + [{"action": action, "ago_min": 0}])[-8:]
            # 活泼度记账：同屋连击 +1 / 换屋归零；在外面就刷新"今天出过门"
            sim.room_streak = (ws.room_streak or 0) + 1 if sim.location == ws.location else 0
            if is_outside(wd, sim.location):
                sim.last_outing_day = today_str
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
                            # goal 牵挂闭合：对应 intent 完成 → resolved（健壮匹配，吸收措辞抖动）
                            th = find_goal_thread(sim.open_threads or [], it["intent"])
                            if th:
                                th["resolved"] = True
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

            # 精力已在 tick 开头按真实时间结算；此处只提交心情变化，不再动 energy。
            await self._state_store.submit_mutation(StateMutation(
                mood_valence_delta=0.01 + event_mood, reason="world loop tick"))
            nstate = await self._state_store.read()
            nstate.energy = settled  # 结算值刚入队未落库，贴回去让快照显示真实精力
        else:
            ws.sim_minutes = sim_minutes
            ws.last_tick = {
                "action": action, "reasoning": reason, "drift": [], "ops": [],
                "micro": micro, "event": None, "sleeping": sleeping,
                "phase": PHASE_ZH.get(phase, phase),
                "real_time": now8.strftime("%H:%M"),
            }
            await self._world_store.write(ws)

        # Phase 5：她空下来/醒来那拍，把睡着或沉浸时漏掉的用户消息捡起来回。
        if WORLD_PRESENCE_GATE_ENABLED:
            try:
                await self._consume_pending(ws, nstate, action)
            except Exception as exc:  # noqa: BLE001
                _log.warning("consume pending error: %s", exc)
            # ④ 收口：没回的消息熬太久 → 她心里挂上「还没回对方消息」；欠的清了→了结。
            try:
                ws.open_threads = reconcile_owe_reply_thread(
                    ws.open_threads or [], ws.pending_messages or [],
                    now=time.time(), today=now8.date().isoformat(),
                    awake=(nstate.energy.status != "sleeping"),
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("owe-reply thread error: %s", exc)

        ws.sim_minutes = sim_minutes  # 写回真实时间，不再累加
        await self._world_store.write(ws)
        return build_snapshot(wd, ws, nstate)

    async def _consume_pending(self, ws, nstate, action: str) -> bool:
        """她醒着、且某条 pending 的冷却已到 → 让她重新面对这条消息，由对话脑临场决定。

        ④：这里不判「要不要回」(那是她对话脑的事)，只管两件物理/节流：
        睡着不捡(她没意识)、她说过「暂不回」的给冷却别每拍打扰。她若仍不想回，再攒一会儿。
        """
        if self._consuming:
            return False  # 上一次还没回完，别重复捡
        if nstate.energy.status == "sleeping":
            return False  # 物理：睡着没意识，不捡
        now = time.time()
        pending = list(ws.pending_messages or [])
        due = [p for p in pending if float(p.get("reconsider_after") or 0.0) <= now]
        if not due:
            return False

        by_session: dict[str, list[dict]] = {}
        for p in due:
            sid = str(p.get("session_id") or "")
            if sid:
                by_session.setdefault(sid, []).append(p)
        if not by_session:
            return False

        # 先认领：把到期条目从 pending 移除并立刻落库（防双发：慢 LLM 期间下一拍读不到这批）。
        claimed_ids = {id(p) for items in by_session.values() for p in items}
        ws.pending_messages = [p for p in pending if id(p) not in claimed_ids]
        await self._world_store.write(ws)

        self._consuming = True
        try:
            from app.services.chat.turn_orchestrator import run_chat_turn_from_persisted_user_messages

            for sid, items in by_session.items():
                msg = "\n".join(str(p.get("message", "")) for p in items if p.get("message"))
                uids = [int(i) for p in items for i in (p.get("user_message_ids") or [])]
                tid = str(items[-1].get("trace_id") or "world_pickup")
                try:
                    result = await asyncio.to_thread(
                        run_chat_turn_from_persisted_user_messages,
                        session_id=sid, message=msg, trace_id=tid,
                        user_message_ids=uids,
                        source=str(items[-1].get("source") or "chat"),
                    )
                    if (result or {}).get("deferred"):
                        # 她重新考虑后仍选择不回 → 重新攒，加冷却，过一阵再让她面对
                        for p in items:
                            p["reconsider_after"] = now + DEFER_COOLDOWN_SECONDS
                        ws.pending_messages = (ws.pending_messages or []) + items
                        continue
                    # 她回应了这些消息 → 把对应的经历从 unspoken 翻成 expressed
                    for p in items:
                        mark_message_experience_expressed(p.get("experience_id"), trace_id=tid)
                    # 平台来源(WX/QQ)：回复经 proactive 链路推回；web/控制台只写 session（刷新可见）。
                    platform = sid.split(":")[0] if ":" in sid else str(items[-1].get("platform") or "")
                    reply = str((result or {}).get("reply") or "").strip()
                    if platform in ("wx", "qq") and reply:
                        from app.services.proactive.send_executor import send_world_expression
                        try:
                            await asyncio.to_thread(
                                send_world_expression, sid, [reply], tid,
                                dry_run=not WORLD_PRESENCE_WX_AUTO_SEND,
                            )
                        except Exception as exc:  # noqa: BLE001
                            _log.warning("world expression send failed sid=%s: %s", sid, exc)
                except Exception as exc:  # noqa: BLE001
                    # 生成失败：回滚进 pending，下一拍再试（认领已落库，不与别处重复）
                    ws.pending_messages = (ws.pending_messages or []) + items
                    _log.warning("pending pickup failed sid=%s, re-stashed: %s", sid, exc)
        finally:
            self._consuming = False
        return True
