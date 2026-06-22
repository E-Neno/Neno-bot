from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_WORLD_JSON = Path(__file__).parent / "virtual_world.json"


class CategoryDef(BaseModel):
    states: list[str]
    default: str


class ObjectDef(BaseModel):
    category: str
    label: str


class WorldDef(BaseModel):
    """静态世界定义：房间、物品、类别→合法状态。封闭世界的白名单。"""

    version: int
    home: str
    categories: dict[str, CategoryDef]
    rooms: dict[str, dict]  # {"bedroom": {"objects": [...]}}
    objects: dict[str, ObjectDef]
    # 刀③ 开放世界：可达图（无向，每条边只写一次）+ 哪些房间算「在外面」。
    # 旧 JSON 缺这两个字段时自动补空 → reachable_rooms 退回「全连通」旧行为，不破坏老世界。
    adjacency: dict[str, list[str]] = Field(default_factory=dict)
    outside: list[str] = Field(default_factory=list)
    # 买东西（刀①收尾）：哪些房间是店——只有人在店里才能 create_object（买）。
    # 旧 JSON 缺这字段时自动补空 → is_shop 恒 False，create_object 退回「任意房间可买」旧行为。
    shops: list[str] = Field(default_factory=list)

    def legal_states(self, obj: str) -> list[str]:
        cat = self.objects[obj].category
        return self.categories[cat].states

    def default_state(self, obj: str) -> str:
        cat = self.objects[obj].category
        return self.categories[cat].default

    def room_of(self, obj: str) -> str | None:
        for room, spec in self.rooms.items():
            if obj in spec.get("objects", []):
                return room
        return None


class WorldState(BaseModel):
    """动态世界状态：存进 life_world_state 单行表。"""

    location: str = "bedroom"
    object_states: dict[str, str] = Field(default_factory=dict)
    updated_at: str = ""
    # 竖切5：跨天延续与防绕圈所需的轻量字段（旧 JSON 缺失自动补默认）
    recent_actions: list[dict] = Field(default_factory=list)  # 最近行动，截断到 ~8
    daily_plan: dict | None = None  # 序列化的 DailyPlan
    sim_minutes: int = 0  # 模拟时钟：当天累计分钟数
    # 竖切6：开放世界（动态物品 / 金钱 / 弃置）
    money: int = 120
    dyn_objects: dict[str, dict] = Field(default_factory=dict)  # {name:{category,room,label}}
    removed: list[str] = Field(default_factory=list)  # 被扔掉的静态物品 key（渲染跳过）
    # 移动东西（意图通道第一刀）：静态物品被挪到别的房间的覆盖表 {obj: room}。
    # 静态物品的房间在不可变 JSON 里定义，relocate 用这张表覆盖；空表=都在定义房间（旧数据自动如此）。
    # 动态物品的房间存在 dyn_objects[name].room 里，不走这张表。
    obj_room_overrides: dict[str, str] = Field(default_factory=dict)
    gone_log: list[dict] = Field(default_factory=list)  # [{object,label,cause,when}]
    # 竖切7：最近一步快照（持久化，端点只读 DB 即可还原"她刚在干嘛"）
    last_tick: dict | None = None
    # 第一刀：跨天牵挂（open thread）。骑现有单行 JSON，旧数据自动补 []。
    open_threads: list[dict] = Field(default_factory=list)
    # 压力触发状态（第二刀 2b：门控 LLM 调用）
    pressure_value: float = 0.0
    pressure_last_wake_ts: float | None = None
    pressure_wakes_this_hour: int = 0
    pressure_hour_anchor: float | None = None
    # Phase 5：睡着/沉浸时漏掉的用户消息，等她空下来/醒来再回（骑现有单行 JSON）。
    # 每条 {session_id, message, user_message_ids, trace_id, source, platform,
    #       chat_type, user_id, received_at, received_sim_min, reconsider_after}
    pending_messages: list[dict] = Field(default_factory=list)
    # 活泼度信号（不写决策，只给 LLM 当"感觉"）：在同一房间连续多少拍、上次出门是哪天。
    room_streak: int = 0
    last_outing_day: str = ""
    # 刀① 阶段 1+2：由已落账状态派生的只读自我语境，旧 JSON 自动补默认。
    self_context: str = ""
    self_context_basis: dict | None = None
    self_context_updated_at: str = ""
    # 意图通道（刀① capstone）：已被她"看见过"的最后一条用户消息经历时间戳。
    # world_loop 只把 cursor 之后的新消息当意图候选喂给世界 LLM，喂过就推进，避免反复重做。
    # 写只在 world_loop（拥有 WorldState 读改写），聊天侧不碰，无并发竞争。旧 JSON 自动补 ""。
    intent_cursor: str = ""
    # 观测性「魂事件流」：让慢热机制可见（你的话到她那了/她学了/挪了/买了）。环形缓冲，最近若干条。
    # 每条 {kind, text, when}。只由 world_loop 追加（拥有 WorldState 写）；自我事实结晶在读端从记忆派生，不进这里。
    soul_events: list[dict] = Field(default_factory=list)


WorldOpType = Literal[
    "set_state", "move", "create_object", "destroy_object", "relocate", "learn",
]


class WorldOp(BaseModel):
    op: WorldOpType
    object: str = ""  # set_state / destroy_object / create_object(新物品 key)
    state: str = ""  # set_state 用
    to_room: str = ""  # move 用
    reason: str = ""
    # 竖切6：开放世界 create_object / destroy_object 用
    category: str = ""
    room: str = ""
    label: str = ""
    cost: int = 0
    cause: str = ""
    # 学习（刀①收尾）：learn 用——她在学/上手的东西，落账后结晶成直接自我事实
    topic: str = ""


class ActionPlan(BaseModel):
    action: str  # 如 "continue_reading"
    reasoning: str = ""
    world_ops: list[WorldOp] = Field(default_factory=list)
    micro_event: str | None = None


def load_world_def() -> WorldDef:
    data = json.loads(_WORLD_JSON.read_text(encoding="utf-8"))
    return WorldDef.model_validate(data)


def seed_world_state(world_def: WorldDef) -> WorldState:
    """所有物品取类别默认状态，location 取第一个房间。"""
    obj_states = {name: world_def.default_state(name) for name in world_def.objects}
    first_room = next(iter(world_def.rooms))
    return WorldState(location=first_room, object_states=obj_states)


def apply_op(world_def: WorldDef, state: WorldState, op: WorldOp) -> WorldState:
    """纯函数：返回应用 op 后的新 WorldState（不校验，校验在 validator）。"""
    new = state.model_copy(deep=True)
    if op.op == "set_state":
        new.object_states[op.object] = op.state
    elif op.op == "move":
        new.location = op.to_room
    elif op.op == "relocate":
        name = op.object
        if name in new.dyn_objects:
            new.dyn_objects[name]["room"] = op.to_room
        elif world_def.room_of(name) == op.to_room:
            new.obj_room_overrides.pop(name, None)  # 挪回老家 → 清掉覆盖，口径干净
        else:
            new.obj_room_overrides[name] = op.to_room
    elif op.op == "learn":
        pass  # 学习是心智动作，不改物理世界；落账走 world_loop 记 learning experience
    elif op.op == "create_object":
        cat = op.category
        new.dyn_objects[op.object] = {
            "category": cat, "room": op.room, "label": op.label or op.object,
        }
        default = world_def.categories[cat].default if cat in world_def.categories else ""
        new.object_states[op.object] = default
        if op.object in new.removed:
            new.removed.remove(op.object)
        new.money -= int(op.cost or 0)
    elif op.op == "destroy_object":
        name = op.object
        label = _label_of(world_def, new, name)
        new.object_states.pop(name, None)
        if name in new.dyn_objects:
            new.dyn_objects.pop(name, None)
        elif name in world_def.objects and name not in new.removed:
            new.removed.append(name)
        from datetime import datetime, timezone
        new.gone_log.append({
            "object": name, "label": label,
            "cause": op.cause or "扔掉", "when": datetime.now(timezone.utc).isoformat(),
        })
    return new


# ── 开放世界访问器（静态 + 动态 + removed 统一口径）─────────────────────────

def _label_of(world_def: WorldDef, state: WorldState, name: str) -> str:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("label", name)
    if name in world_def.objects:
        return world_def.objects[name].label
    return name


def obj_exists(world_def: WorldDef, state: WorldState, name: str) -> bool:
    if name in state.removed:
        return False
    return name in state.dyn_objects or name in world_def.objects


def obj_category(world_def: WorldDef, state: WorldState, name: str) -> str | None:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("category")
    if name in world_def.objects:
        return world_def.objects[name].category
    return None


def obj_room(world_def: WorldDef, state: WorldState, name: str) -> str | None:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("room")
    if name in state.obj_room_overrides:  # 移动东西：静态物品被挪过
        return state.obj_room_overrides[name]
    return world_def.room_of(name)


def legal_states_of(world_def: WorldDef, state: WorldState, name: str) -> list[str]:
    cat = obj_category(world_def, state, name)
    if cat and cat in world_def.categories:
        return world_def.categories[cat].states
    return []


def objects_in_room(world_def: WorldDef, state: WorldState, room: str) -> list[str]:
    overrides = state.obj_room_overrides
    # 本房间定义的静态物品，去掉被扔掉的、被挪走的
    items = [
        o for o in world_def.rooms.get(room, {}).get("objects", [])
        if o not in state.removed and overrides.get(o, room) == room
    ]
    # 被挪进本房间的静态物品（定义房间在别处）
    items += [
        o for o, r in overrides.items()
        if r == room and o not in state.removed
        and o in world_def.objects and world_def.room_of(o) != room
    ]
    items += [n for n, meta in state.dyn_objects.items() if meta.get("room") == room]
    return items


def room_count(world_def: WorldDef, state: WorldState, room: str) -> int:
    return len(objects_in_room(world_def, state, room))


# ── 刀③ 可达性 / 在外面 ──────────────────────────────────────────────────────

def reachable_rooms(world_def: WorldDef, state: WorldState, room: str) -> list[str]:
    """从 room 一步可达的房间（无向图）。

    adjacency 为空时退回旧行为「除当前房间外全部可达」，老世界/老测试不受影响。
    state 入参保留以备将来动态可达（如锁门），当前未用。
    """
    adj = world_def.adjacency
    if not adj:
        return [r for r in world_def.rooms if r != room]
    out: set[str] = set(adj.get(room, []))
    for src, nbrs in adj.items():          # 无向：反向边也算可达
        if room in nbrs:
            out.add(src)
    return [r for r in world_def.rooms if r in out and r != room]


def is_outside(world_def: WorldDef, room: str) -> bool:
    """该房间是否算「在外面」（出了家门）。"""
    return room in set(world_def.outside or [])


def is_shop(world_def: WorldDef, room: str) -> bool:
    """该房间是否是店（只有人在店里才能买东西）。shops 为空时恒 False（退回旧「任意房间可买」）。"""
    return room in set(world_def.shops or [])


def next_step_toward(world_def: WorldDef, state: WorldState, src: str, dst: str) -> str | None:
    """BFS：从 src 朝 dst 走的最短路下一跳房间。已在 dst / 无路 → None。

    用 `reachable_rooms` 当邻接（含出门要过玄关那套门控）。给「困了不在卧室先回卧室」用。
    """
    if src == dst:
        return None
    from collections import deque
    visited = {src}
    queue: deque[tuple[str, str]] = deque()  # (room, 第一步)
    for nb in reachable_rooms(world_def, state, src):
        if nb not in visited:
            visited.add(nb)
            queue.append((nb, nb))
    while queue:
        room, first = queue.popleft()
        if room == dst:
            return first
        for nb in reachable_rooms(world_def, state, room):
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, first))
    return None


# ── 牵挂工具（第一刀：跨天 open thread）──────────────────────────────────────

def make_thread(kind: str, topic: str, *, day: str, intensity: float, mood: str = "") -> dict:
    """创建一条牵挂 dict。id 用于去重。"""
    if kind == "loss":
        tid = f"loss:{topic}"
    elif kind == "goal":
        tid = f"goal:{topic}"
    else:
        tid = f"residue:{topic}"
    return {
        "id": tid,
        "kind": kind,
        "topic": topic,
        "intensity": intensity,
        "mood": mood,
        "born_day": day,
        "last_touch_day": day,
        "carry_count": 0,
        "resolved": False,
    }


def find_thread(threads: list[dict], tid: str) -> dict | None:
    """按 id 查找牵挂；未找到返回 None。"""
    for t in threads:
        if t.get("id") == tid:
            return t
    return None


def push_soul_event(events: list[dict], kind: str, text: str, *, when: str, cap: int = 15) -> list[dict]:
    """往魂事件流追加一条（环形缓冲）。纯函数。

    连续重复（同 kind+text）不重记——滑行接续/反复同一动作不该刷屏。
    """
    out = list(events or [])
    text = str(text or "").strip()
    if not text:
        return out
    if out and out[-1].get("kind") == kind and out[-1].get("text") == text:
        return out
    out.append({"kind": kind, "text": text, "when": when})
    return out[-cap:]


_OWE_REPLY_ID = "goal:还没回对方消息"


def reconcile_owe_reply_thread(
    threads: list[dict],
    pending: list[dict] | None,
    *,
    now: float,
    today: str,
    threshold: float = 3600.0,
    awake: bool = True,
) -> list[dict]:
    """没回的消息熬太久 → 她心里挂上「还没回对方消息」；欠的都清了 → 了结。纯函数。

    ④ 收口：把 unspoken/pending 这个状态变成她真能感到的重量——一条未竟牵挂，会在
    self_state 里冒出来惦记着。只在她醒着、且有 pending 超过 threshold 时挂；不靠规则判语气。
    """
    out = list(threads or [])
    existing = find_thread(out, _OWE_REPLY_ID)
    owed = [
        p for p in (pending or [])
        if (now - float(p.get("received_at") or now)) >= threshold
    ]
    if awake and owed:
        if existing:
            if not existing.get("resolved"):
                existing["last_touch_day"] = today
        else:
            t = make_thread("goal", "还没回对方消息", day=today,
                            intensity=0.45, mood="有点过意不去")
            t["carry_count"] = 2  # 现成 self_state 过滤器要 carry>=2 才显；这是当下的惦记，直接算活跃
            out.append(t)
    else:
        # 没有欠太久的了 → 她算「回上了/不欠了」，了结
        if existing and not existing.get("resolved"):
            existing["resolved"] = True
    return out


_PUNCT_RE = re.compile(r"[\s，。、！？,.!?…·；;：:\"'""'']+")


def _norm_intent(s: str) -> str:
    """归一化意图文本：去标点与空白，便于跨措辞匹配。"""
    return _PUNCT_RE.sub("", s or "")


def _bigram_jaccard(a: str, b: str) -> float:
    """字符二元组 Jaccard 相似度，用于吸收 LLM 措辞抖动。"""
    ba = {a[i:i + 2] for i in range(len(a) - 1)}
    bb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not ba or not bb:
        return 1.0 if a == b else 0.0
    union = len(ba | bb)
    return len(ba & bb) / union if union else 0.0


def find_goal_thread(threads: list[dict], intent: str, *, threshold: float = 0.5) -> dict | None:
    """为「未竟」goal 找已有牵挂，比 exact id 健壮。

    匹配规则（保守，宁可不并也不误并不同目标）：
      1. 归一化后相等 / 互为子串 → 命中
      2. 否则取字符 bigram Jaccard 最高者；≥ threshold 才算同一目标
    这样 LLM planner 每天措辞抖动（"把那本书读完" / "读完那本书"）仍能累积 carry_count。
    """
    target = _norm_intent(intent)
    if not target:
        return None
    best: dict | None = None
    best_score = 0.0
    for t in threads:
        if t.get("kind") != "goal" or t.get("resolved"):
            continue
        cand = _norm_intent(t.get("topic", ""))
        if not cand:
            continue
        if cand == target or cand in target or target in cand:
            return t
        score = _bigram_jaccard(cand, target)
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= threshold else None
