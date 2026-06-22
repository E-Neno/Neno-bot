# Living World 竖切1（封闭世界）实现计划

> **历史实施记录。** 当前实现已进入正式 `WorldLoop` 并接入应用；
> 现状与运行方式见 `docs/living-world.md`，不要按本文的“独立 dry-run、未接 scheduler”描述判断当前系统。

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。
>
> **本计划由 CC（设计+质检方）编写。竖切1 由 CC 亲手实现，作为"黄金模板"。竖切2 起的实现任务才下放给 GPT-5.5/codex，照本模板填写，CC 逐行审、用户肉眼验。**

**目标：** 给 Neno 一个真实存在、会自行变化的封闭世界（固定房间+物品，只变状态），并打通"世界漂移 → 读世界 → 决策(LLM mock) → 校验 → 执行落账"这一根垂直管道，让人能跑一条命令、亲眼看到世界在变。

**架构：** 世界 = 静态定义（`virtual_world.json`，房间/物品/合法状态）+ 动态状态（SQLite 单行 JSON 表 `life_world_state`）。每个 tick 先跑确定性漂移（水壶变凉等），再把世界+记忆喂给 WorldBrain；竖切1 的 WorldBrain **不调真实模型**，返回 mock 的 ActionPlan；ActionPlan 里的 `world_ops` 经 action_validator 逐条校验后由 world_store 落账。LLM 部分留好接口、用开关 `world_llm_enabled`（默认 False）守住。

**技术栈：** Python 3.11+ / Pydantic v2 / SQLite（`app/storage/db.py`）/ pytest。复用现有 `ConsciousnessConfig`、`db_storage`、`ActivityEpisodeStore` 的存储写法。

---

## 0. 硬约束（覆盖 skill 默认行为，必须遵守）

- **不 commit、不 push。** skill 默认的"频繁 commit"步骤全部替换为"验证检查点（不 commit）"。集成提交时机由用户单独下令。
- **不调真实模型。** 竖切1 的 WorldBrain 仅返回 mock ActionPlan；`world_llm_enabled` 默认 False，True 分支在竖切3 才实现。
- **不碰红线文件：** `session_submit_controller.py`、`session_aggregation_controller.py`、`chat/context_builder.py`、`chat_service.py`、`proactive/rules.py`、`chat/history_digest.py`。
- **单机 SQLite。** 不引入 Redis/Kafka/Celery/Postgres。
- **⚠️ 新表需用户明确放行：** 本计划新增 `life_world_state` 表。C1.5 期有"不新增表"约束，执行本计划前需用户明确解除该约束（仅针对本表）。未放行则任务 2 暂停。
- **不注册 scheduler、不接 LifeLoop 主链路。** 竖切1 只交付独立可跑的 dry-run 脚本，不改 `life_loop.py`、不改 `world_engine.py`。接线在竖切4。

---

## 1. 反作弊验收契约（codex 不可狡辩的"做完"定义）

竖切1 算完成，当且仅当**人能跑一条命令 `python scripts/world_slice1_dryrun.py`**，并逐条勾选：

- [ ] 输出显示 Neno 在某个真实房间（来自 `virtual_world.json`）。
- [ ] 输出显示某物品因**漂移**而改状态（例：`kettle: warm → cold`），且该变化**不是** mock ActionPlan 造成的。
- [ ] 输出显示 mock ActionPlan 的 `world_ops`，且每条 op 标注校验结果（accepted/rejected + 原因）。
- [ ] 一条 `set_state` op 被接受后，`life_world_state` 里对应物品状态**真的变了**（再次读库可见）。
- [ ] 一条**非法** op（引用不存在的物品 / 不在当前房间 / 非法目标状态）被 validator **拒绝**，世界**未被改动**。
- [ ] 连跑两次脚本，状态**持久**（第二次读到的是第一次落账后的结果，不是初始值）。
- [ ] 全程无任何真实模型调用（grep 输出确认无 httpx/openai 实际请求）。

**反作弊条款（审查时逐条抓）：**
- [ ] 禁止任何 `placeholder` / `TODO` / `pass  # later` / "Phase X will replace" 注释。
- [ ] 每个被接受的 `world_op` 必须真的写库；禁止"只 log 不落账"。
- [ ] 漂移函数必须真的改变状态值；禁止 `return state` 原样返回。
- [ ] 测试必须断言**状态的实际变化值**（如 `assert after["kettle"] == "cold"`）；禁止只断言"函数被调用过"或只断言 `success is True`。
- [ ] validator 拒绝路径必须有测试覆盖，并断言世界**未变**。

---

## 2. 文件结构与职责

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `app/services/consciousness/virtual_world.json` | 静态世界：房间→物品、物品类别、类别→合法状态。封闭世界的白名单。 | 新建 |
| `app/services/consciousness/world_model.py` | 加载并校验 `virtual_world.json`；定义 `WorldDef`、`WorldState`、`WorldOp`、`ActionPlan` 等 Pydantic 模型；纯函数 `apply_op`。 | 新建 |
| `app/storage/db.py` | 在 `init_db()` 内新增 `CREATE TABLE IF NOT EXISTS life_world_state`。 | 修改（仅加表，约 `init_db` 末尾 +12 行） |
| `app/services/consciousness/world_store.py` | 读写 `life_world_state` 单行表；首次读返回种子状态；坏 JSON 降级。 | 新建 |
| `app/services/consciousness/world_drift.py` | 确定性衰减：基于时间间隔把物品状态向"自然趋势"推进（水壶变凉等）。纯函数。 | 新建 |
| `app/services/consciousness/action_validator.py` | 校验 `ActionPlan.world_ops`：物品存在？在当前房间？目标状态合法？返回 accepted/rejected 列表。 | 新建 |
| `app/services/consciousness/world_brain.py` | 构建 tick 上下文 prompt；`world_llm_enabled=False` 时返回 mock ActionPlan（确定性）。 | 新建 |
| `app/services/consciousness/config.py` | 新增 `world_llm_enabled`、`world_decay_*` 开关。 | 修改（+约 5 行） |
| `scripts/world_slice1_dryrun.py` | 验收脚本：跑一轮完整管道并打印，供肉眼勾选验收契约。 | 新建 |
| `tests/unit/test_world_model.py` | `virtual_world.json` 可加载、`apply_op` 行为。 | 新建 |
| `tests/unit/test_world_store.py` | 读写、种子、持久、坏 JSON 降级。 | 新建 |
| `tests/unit/test_world_drift.py` | 衰减真的改状态、未到时间不改、幂等边界。 | 新建 |
| `tests/unit/test_action_validator.py` | 接受合法 op、拒绝三类非法 op、拒绝路径不改世界。 | 新建 |

按职责拆分，每个文件单一职责，便于 codex 后续照模板填写。

---

## 3. 数据模型与世界定义

### 3.1 `virtual_world.json`（4 房间 + 15 物品，默认安静小公寓；数量是配置，可改）

```json
{
  "version": 1,
  "home": "neno_apartment",
  "categories": {
    "drinkware": { "states": ["clean", "dirty", "broken"], "default": "clean" },
    "appliance": { "states": ["cold", "warm", "boiling"], "default": "cold" },
    "furniture": { "states": ["tidy", "rumpled"], "default": "tidy" },
    "plant":     { "states": ["fresh", "needs_water", "wilting", "dead"], "default": "fresh" },
    "device":    { "states": ["silent", "has_unread"], "default": "silent" },
    "book":      { "states": ["closed", "reading", "finished"], "default": "closed" },
    "window":    { "states": ["bright", "dim", "dark"], "default": "bright" },
    "light":     { "states": ["off", "on"], "default": "off" }
  },
  "rooms": {
    "bedroom":     { "objects": ["bed", "desk", "bookshelf", "phone", "window_bed", "lamp"] },
    "kitchen":     { "objects": ["kettle", "mug", "fridge"] },
    "living_room": { "objects": ["sofa", "book", "tv", "ceiling_light"] },
    "balcony":     { "objects": ["chair", "plants"] }
  },
  "objects": {
    "bed":           { "category": "furniture", "label": "床" },
    "desk":          { "category": "furniture", "label": "书桌" },
    "bookshelf":     { "category": "furniture", "label": "书架" },
    "phone":         { "category": "device",    "label": "手机" },
    "window_bed":    { "category": "window",    "label": "卧室窗" },
    "lamp":          { "category": "light",     "label": "台灯" },
    "kettle":        { "category": "appliance", "label": "水壶" },
    "mug":           { "category": "drinkware", "label": "马克杯" },
    "fridge":        { "category": "appliance", "label": "冰箱" },
    "sofa":          { "category": "furniture", "label": "沙发" },
    "book":          { "category": "book",      "label": "书" },
    "tv":            { "category": "device",    "label": "电视" },
    "ceiling_light": { "category": "light",     "label": "客厅灯" },
    "chair":         { "category": "furniture", "label": "阳台椅" },
    "plants":        { "category": "plant",     "label": "盆栽" }
  }
}
```

### 3.2 Pydantic 模型（`world_model.py`，竖切1 用到的部分）

```python
from __future__ import annotations
import json
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
    version: int
    home: str
    categories: dict[str, CategoryDef]
    rooms: dict[str, dict]            # {"bedroom": {"objects": [...]}}
    objects: dict[str, ObjectDef]

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


WorldOpType = Literal["set_state", "move"]


class WorldOp(BaseModel):
    op: WorldOpType
    object: str = ""        # set_state 用
    state: str = ""         # set_state 用
    to_room: str = ""       # move 用
    reason: str = ""


class ActionPlan(BaseModel):
    action: str                       # 如 "continue_reading"
    reasoning: str = ""
    world_ops: list[WorldOp] = Field(default_factory=list)
    micro_event: str | None = None


def load_world_def() -> WorldDef:
    data = json.loads(_WORLD_JSON.read_text(encoding="utf-8"))
    return WorldDef.model_validate(data)


def seed_world_state(world_def: WorldDef) -> WorldState:
    """所有物品取类别默认状态，location 取第一个房间。"""
    obj_states = {
        name: world_def.default_state(name) for name in world_def.objects
    }
    first_room = next(iter(world_def.rooms))
    return WorldState(location=first_room, object_states=obj_states)


def apply_op(world_def: WorldDef, state: WorldState, op: WorldOp) -> WorldState:
    """纯函数：返回应用 op 后的新 WorldState（不校验，校验在 validator）。"""
    new = state.model_copy(deep=True)
    if op.op == "set_state":
        new.object_states[op.object] = op.state
    elif op.op == "move":
        new.location = op.to_room
    return new
```

---

## 任务 1：静态世界定义 + world_model 加载/apply

**文件：**
- 创建：`app/services/consciousness/virtual_world.json`（内容见 3.1）
- 创建：`app/services/consciousness/world_model.py`（内容见 3.2）
- 测试：`tests/unit/test_world_model.py`

- [ ] **步骤 1：写 `virtual_world.json`**（粘贴 3.1 全文）

- [ ] **步骤 2：写失败测试**

```python
# tests/unit/test_world_model.py
from app.services.consciousness.world_model import (
    load_world_def, seed_world_state, apply_op, WorldOp,
)


def test_world_def_loads_and_indexes():
    wd = load_world_def()
    assert wd.room_of("kettle") == "kitchen"
    assert "cold" in wd.legal_states("kettle")
    assert wd.default_state("kettle") == "cold"


def test_seed_state_uses_defaults():
    wd = load_world_def()
    st = seed_world_state(wd)
    assert st.object_states["plants"] == "fresh"
    assert st.location in wd.rooms


def test_apply_set_state_returns_changed_copy():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="set_state", object="kettle", state="boiling"))
    assert out.object_states["kettle"] == "boiling"
    assert st.object_states["kettle"] == "cold"   # 原对象不被改（纯函数）


def test_apply_move_changes_location():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="move", to_room="balcony"))
    assert out.location == "balcony"
```

- [ ] **步骤 3：运行验证失败**

运行：`pytest tests/unit/test_world_model.py -v`
预期：FAIL（模块/函数不存在）

- [ ] **步骤 4：写 `world_model.py`**（粘贴 3.2 全文）

- [ ] **步骤 5：运行验证通过**

运行：`pytest tests/unit/test_world_model.py -v`
预期：4 passed

- [ ] **步骤 6：验证检查点（不 commit）**

运行：`python -c "from app.services.consciousness.world_model import load_world_def; print(load_world_def().home)"`
预期：打印 `neno_apartment`

---

## 任务 2：`life_world_state` 表 + world_store（⚠️ 需用户放行新表）

**前置：** 用户已明确解除"不新增表"约束（仅针对本表）。否则停。

**文件：**
- 修改：`app/storage/db.py`（`init_db()` 内新增建表）
- 创建：`app/services/consciousness/world_store.py`
- 测试：`tests/unit/test_world_store.py`

- [ ] **步骤 1：在 `db.py::init_db()` 末尾新增建表**（与现有 `CREATE TABLE IF NOT EXISTS` 同风格）

```python
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS life_world_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
            """
        )
```

- [ ] **步骤 2：写失败测试**

```python
# tests/unit/test_world_store.py
import asyncio
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_model import load_world_def


def test_first_read_returns_seed(tmp_db):   # tmp_db: 见下方 fixture 说明
    store = WorldStore()
    state = asyncio.run(store.read())
    assert state.object_states["kettle"] == "cold"   # 种子默认


def test_write_then_read_persists(tmp_db):
    store = WorldStore()
    state = asyncio.run(store.read())
    state.object_states["kettle"] = "boiling"
    asyncio.run(store.write(state))
    again = asyncio.run(store.read())
    assert again.object_states["kettle"] == "boiling"


def test_bad_json_degrades_to_seed(tmp_db):
    from app.storage import db as db_storage
    with db_storage.get_conn() as conn:
        conn.execute(
            "INSERT INTO life_world_state (id, state_json, updated_at) "
            "VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
            ("{not json", "2026-06-07T00:00:00+00:00"),
        )
    store = WorldStore()
    state = asyncio.run(store.read())   # 不抛异常，降级到种子
    assert state.object_states["kettle"] == "cold"
```

> **fixture 说明（写进 `tests/unit/conftest.py` 或复用现有）：** `tmp_db` 需把 `db_storage.DB_PATH` 指向临时文件并调用 `init_db()`。若仓库已有等价 fixture（检查 `tests/unit/conftest.py`），直接复用，勿重复定义。

- [ ] **步骤 3：运行验证失败**

运行：`pytest tests/unit/test_world_store.py -v`
预期：FAIL（`WorldStore` 不存在）

- [ ] **步骤 4：写 `world_store.py`**

```python
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone

from app.storage import db as db_storage
from .world_model import WorldState, WorldDef, load_world_def, seed_world_state


class WorldStore:
    def __init__(self, world_def: WorldDef | None = None) -> None:
        self._world_def = world_def or load_world_def()

    async def read(self) -> WorldState:
        return await asyncio.to_thread(self._read_sync)

    async def write(self, state: WorldState) -> None:
        await asyncio.to_thread(self._write_sync, state)

    def _read_sync(self) -> WorldState:
        row = db_storage.fetch_one(
            "SELECT state_json FROM life_world_state WHERE id = 1"
        )
        if row is None:
            seed = seed_world_state(self._world_def)
            self._write_sync(seed)
            return seed
        try:
            data = json.loads(row["state_json"])
            state = WorldState.model_validate(data)
            if not state.object_states:        # 空也视为需种子
                raise ValueError("empty world state")
            return state
        except Exception:
            return seed_world_state(self._world_def)   # 坏 JSON 降级

    def _write_sync(self, state: WorldState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(state.model_dump(), ensure_ascii=False)
        db_storage.execute_write(
            """
            INSERT INTO life_world_state (id, state_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (payload, state.updated_at),
        )
```

- [ ] **步骤 5：运行验证通过**

运行：`pytest tests/unit/test_world_store.py -v`
预期：3 passed

- [ ] **步骤 6：验证检查点（不 commit）** — 确认无红线文件改动：

运行：`git diff --name-only -- app/services/chat/context_builder.py app/services/chat_service.py`
预期：空输出

---

## 任务 3：world_drift 确定性漂移（"活"的核心）

**文件：**
- 创建：`app/services/consciousness/world_drift.py`
- 修改：`app/services/consciousness/config.py`（新增漂移阈值）
- 测试：`tests/unit/test_world_drift.py`

漂移规则（竖切1 范围，纯确定性，与真实时钟解耦——以"分钟数"为入参便于测试）：

| 物品类别 | 当前态 | 经过 N 分钟后 → | 阈值 |
|---|---|---|---|
| appliance（水壶） | warm/boiling | cold | ≥30 min |
| plant（盆栽） | fresh | needs_water | ≥ (2×1440) min |
| plant | needs_water | wilting | ≥ (1×1440) min |

- [ ] **步骤 1：在 `config.py` 新增开关**

```python
    # Living World 竖切1
    world_llm_enabled: bool = _env_bool("CONSCIOUSNESS_WORLD_LLM_ENABLED", False)
    world_kettle_cool_minutes: int = 30
    world_plant_dry_minutes: int = 2880      # 2 天
    world_plant_wilt_minutes: int = 1440     # 再 1 天
```

- [ ] **步骤 2：写失败测试**

```python
# tests/unit/test_world_drift.py
from app.services.consciousness.world_model import load_world_def, seed_world_state
from app.services.consciousness.world_drift import apply_drift
from app.services.consciousness.config import ConsciousnessConfig


def _setup():
    wd = load_world_def()
    st = seed_world_state(wd)
    return wd, st, ConsciousnessConfig()


def test_warm_kettle_cools_after_threshold():
    wd, st, cfg = _setup()
    st.object_states["kettle"] = "warm"
    out, changed = apply_drift(wd, st, elapsed_minutes=31, config=cfg)
    assert out.object_states["kettle"] == "cold"
    assert ("kettle", "warm", "cold") in changed


def test_kettle_not_cooled_before_threshold():
    wd, st, cfg = _setup()
    st.object_states["kettle"] = "warm"
    out, changed = apply_drift(wd, st, elapsed_minutes=10, config=cfg)
    assert out.object_states["kettle"] == "warm"
    assert changed == []


def test_cold_kettle_is_stable():
    wd, st, cfg = _setup()
    out, changed = apply_drift(wd, st, elapsed_minutes=999, config=cfg)
    assert out.object_states["kettle"] == "cold"   # 已冷不再变


def test_fresh_plant_needs_water_after_two_days():
    wd, st, cfg = _setup()
    out, changed = apply_drift(wd, st, elapsed_minutes=2881, config=cfg)
    assert out.object_states["plants"] == "needs_water"
```

- [ ] **步骤 3：运行验证失败**

运行：`pytest tests/unit/test_world_drift.py -v`
预期：FAIL（`apply_drift` 不存在）

- [ ] **步骤 4：写 `world_drift.py`**

```python
from __future__ import annotations
from .world_model import WorldDef, WorldState
from .config import ConsciousnessConfig


def apply_drift(
    world_def: WorldDef,
    state: WorldState,
    *,
    elapsed_minutes: float,
    config: ConsciousnessConfig,
) -> tuple[WorldState, list[tuple[str, str, str]]]:
    """确定性漂移。返回 (新状态, 变化列表[(object, from, to)])。

    纯函数：不读时钟、不写库。elapsed_minutes 由调用方计算。
    """
    new = state.model_copy(deep=True)
    changed: list[tuple[str, str, str]] = []

    def _set(obj: str, target: str) -> None:
        cur = new.object_states.get(obj)
        if cur is not None and cur != target:
            new.object_states[obj] = target
            changed.append((obj, cur, target))

    # 水壶：warm/boiling → cold
    if new.object_states.get("kettle") in {"warm", "boiling"}:
        if elapsed_minutes >= config.world_kettle_cool_minutes:
            _set("kettle", "cold")

    # 盆栽：fresh → needs_water → wilting
    plant = new.object_states.get("plants")
    if plant == "fresh" and elapsed_minutes >= config.world_plant_dry_minutes:
        _set("plants", "needs_water")
    elif plant == "needs_water" and elapsed_minutes >= config.world_plant_wilt_minutes:
        _set("plants", "wilting")

    return new, changed
```

- [ ] **步骤 5：运行验证通过**

运行：`pytest tests/unit/test_world_drift.py -v`
预期：4 passed

- [ ] **步骤 6：验证检查点（不 commit）**

---

## 任务 4：action_validator 守门

**文件：**
- 创建：`app/services/consciousness/action_validator.py`
- 测试：`tests/unit/test_action_validator.py`

- [ ] **步骤 1：写失败测试**

```python
# tests/unit/test_action_validator.py
from app.services.consciousness.world_model import (
    load_world_def, seed_world_state, WorldOp,
)
from app.services.consciousness.action_validator import validate_ops


def _setup():
    wd = load_world_def()
    st = seed_world_state(wd)
    st.location = "kitchen"   # 当前在厨房
    return wd, st


def test_accepts_legal_set_state_in_current_room():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="kettle", state="boiling")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op]
    assert rejected == []


def test_rejects_unknown_object():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="dragon", state="boiling")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert rejected[0][0] == op
    assert "unknown_object" in rejected[0][1]


def test_rejects_object_not_in_current_room():
    wd, st = _setup()   # 在厨房
    op = WorldOp(op="set_state", object="book", state="reading")  # book 在客厅
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "not_in_current_room" in rejected[0][1]


def test_rejects_illegal_state():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="kettle", state="exploded")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "illegal_state" in rejected[0][1]


def test_rejects_move_to_unknown_room():
    wd, st = _setup()
    op = WorldOp(op="move", to_room="dungeon")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "unknown_room" in rejected[0][1]
```

- [ ] **步骤 2：运行验证失败**

运行：`pytest tests/unit/test_action_validator.py -v`
预期：FAIL（`validate_ops` 不存在）

- [ ] **步骤 3：写 `action_validator.py`**

```python
from __future__ import annotations
from .world_model import WorldDef, WorldState, WorldOp


def validate_ops(
    world_def: WorldDef,
    state: WorldState,
    ops: list[WorldOp],
) -> tuple[list[WorldOp], list[tuple[WorldOp, str]]]:
    """逐条校验。返回 (accepted, rejected[(op, reason)])。"""
    accepted: list[WorldOp] = []
    rejected: list[tuple[WorldOp, str]] = []

    for op in ops:
        reason = _check(world_def, state, op)
        if reason is None:
            accepted.append(op)
        else:
            rejected.append((op, reason))
    return accepted, rejected


def _check(world_def: WorldDef, state: WorldState, op: WorldOp) -> str | None:
    if op.op == "set_state":
        if op.object not in world_def.objects:
            return "unknown_object"
        if world_def.room_of(op.object) != state.location:
            return "not_in_current_room"
        if op.state not in world_def.legal_states(op.object):
            return "illegal_state"
        return None
    if op.op == "move":
        if op.to_room not in world_def.rooms:
            return "unknown_room"
        return None
    return "unknown_op"
```

- [ ] **步骤 4：运行验证通过**

运行：`pytest tests/unit/test_action_validator.py -v`
预期：5 passed

- [ ] **步骤 5：验证检查点（不 commit）**

---

## 任务 5：world_brain（mock 决策，留好 LLM 接口）

**文件：**
- 创建：`app/services/consciousness/world_brain.py`
- 测试：并入 `scripts/world_slice1_dryrun.py` 的肉眼验收（mock 决策无需单测断言其"内容"，只需确定性）

- [ ] **步骤 1：写 `world_brain.py`**

```python
from __future__ import annotations
from .config import ConsciousnessConfig
from .world_model import WorldDef, WorldState, ActionPlan, WorldOp


class WorldBrain:
    """竖切1：world_llm_enabled=False → 返回确定性 mock ActionPlan。
    True 分支（真实 GPT-4o-mini）在竖切3 实现，当前显式拒绝。
    """

    def __init__(self, world_def: WorldDef, config: ConsciousnessConfig) -> None:
        self._world_def = world_def
        self._config = config

    def build_prompt(self, state: WorldState) -> str:
        """把当前世界（房间+在场物品+状态）拼成可读上下文。竖切3 喂给真实模型。"""
        room = state.location
        objs = self._world_def.rooms.get(room, {}).get("objects", [])
        lines = [f"Neno 现在在：{room}", "周围的东西："]
        for o in objs:
            label = self._world_def.objects[o].label if o in self._world_def.objects else o
            st = state.object_states.get(o, "?")
            lines.append(f"  - {label}（{st}）")
        return "\n".join(lines)

    async def decide(self, state: WorldState) -> ActionPlan:
        if self._config.world_llm_enabled:
            raise RuntimeError(
                "real world LLM is disabled in slice1; implement in slice3 with mock in tests"
            )
        return self._mock_decide(state)

    def _mock_decide(self, state: WorldState) -> ActionPlan:
        """确定性 mock：若在厨房且水壶非 boiling，就烧水；否则去客厅读书。"""
        if state.location == "kitchen" and state.object_states.get("kettle") != "boiling":
            return ActionPlan(
                action="boil_water",
                reasoning="(mock) 水壶凉了，烧点水",
                world_ops=[WorldOp(op="set_state", object="kettle", state="boiling",
                                   reason="烧水")],
                micro_event="等水开的时候发了会呆",
            )
        return ActionPlan(
            action="read_book",
            reasoning="(mock) 去客厅接着读书",
            world_ops=[
                WorldOp(op="move", to_room="living_room", reason="换到客厅"),
                WorldOp(op="set_state", object="book", state="reading", reason="翻开书"),
            ],
            micro_event="读得有点入神",
        )
```

> 注意：`_mock_decide` 第二分支先 move 到 living_room 再对 book set_state——验证器是**逐条按当前 state 校验**，因此 dry-run 执行器必须**每接受一条 op 就更新 state 再校验下一条**（见任务 6 执行循环），否则 book 会因"不在当前房间"被拒。这是竖切1 要暴露并处理的真实顺序依赖。

- [ ] **步骤 2：验证检查点（不 commit）**

运行：`python -c "import app.services.consciousness.world_brain"`
预期：无报错

---

## 任务 6：dry-run 验收脚本（肉眼验收的载体）

**文件：**
- 创建：`scripts/world_slice1_dryrun.py`

- [ ] **步骤 1：写脚本**

```python
"""Living World 竖切1 dry-run 验收脚本。
跑一轮：漂移 → 读世界 → mock决策 → 逐条校验+执行 → 落账 → 打印。
不调真实模型。运行：python scripts/world_slice1_dryrun.py
"""
import asyncio

from app.storage.db import init_db
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import (
    load_world_def, apply_op,
)
from app.services.consciousness.world_store import WorldStore
from app.services.consciousness.world_drift import apply_drift
from app.services.consciousness.action_validator import validate_ops
from app.services.consciousness.world_brain import WorldBrain


async def main() -> None:
    init_db()
    cfg = ConsciousnessConfig()
    wd = load_world_def()
    store = WorldStore(wd)
    brain = WorldBrain(wd, cfg)

    state = await store.read()
    print("=== 读入世界 ===")
    print(f"location={state.location}")
    print(f"kettle={state.object_states.get('kettle')} plants={state.object_states.get('plants')}")

    # 模拟距上次 45 分钟：水壶若 warm 会凉
    state.object_states.setdefault("kettle", "warm")
    if state.object_states["kettle"] == "cold":
        state.object_states["kettle"] = "warm"   # 制造可观测漂移
    drifted, changes = apply_drift(wd, state, elapsed_minutes=45, config=cfg)
    print("\n=== 世界漂移（非决策造成）===")
    for obj, frm, to in changes:
        print(f"  {obj}: {frm} -> {to}")
    state = drifted

    print("\n=== 当前上下文（将来喂给 LLM）===")
    print(brain.build_prompt(state))

    plan = await brain.decide(state)
    print("\n=== mock 决策 ActionPlan ===")
    print(f"action={plan.action} reasoning={plan.reasoning}")
    print(f"micro_event={plan.micro_event}")

    print("\n=== 逐条校验 + 执行（顺序依赖：执行后再校验下一条）===")
    for op in plan.world_ops:
        accepted, rejected = validate_ops(wd, state, [op])
        if accepted:
            state = apply_op(wd, state, op)
            print(f"  ACCEPT {op.op} {op.object or op.to_room} -> {op.state or ''}")
        else:
            _, reason = rejected[0]
            print(f"  REJECT {op.op} {op.object or op.to_room} ({reason})")

    # 故意插一条非法 op，证明守门有效
    from app.services.consciousness.world_model import WorldOp
    bad = WorldOp(op="set_state", object="dragon", state="boiling")
    _, rej = validate_ops(wd, state, [bad])
    print(f"  REJECT(故意) set_state dragon ({rej[0][1]}) —— 世界未变")

    await store.write(state)
    after = await store.read()
    print("\n=== 落账后世界（持久）===")
    print(f"location={after.location}")
    print(f"kettle={after.object_states.get('kettle')} book={after.object_states.get('book')}")
    print("\n再次运行本脚本，应看到状态从这里接着变（持久性验收）。")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **步骤 2：运行验收脚本**

运行：`python scripts/world_slice1_dryrun.py`
预期：完整打印漂移、决策、校验、落账；对照第 1 节验收契约逐条勾选。

- [ ] **步骤 3：全量回归 + 红线检查（验证检查点，不 commit）**

运行：
```bash
pytest tests/unit/test_world_model.py tests/unit/test_world_store.py \
       tests/unit/test_world_drift.py tests/unit/test_action_validator.py -v
pytest tests/unit/test_brain.py tests/unit/test_state_store.py \
       tests/unit/test_reflection_engine.py -v   # 确认未误伤现有
git diff --name-only -- \
  app/services/session_submit_controller.py \
  app/services/session_aggregation_controller.py \
  app/services/chat/context_builder.py \
  app/services/chat_service.py \
  app/services/proactive/rules.py \
  app/services/chat/history_digest.py
```
预期：新测试全过；现有回归全过；红线 diff 为空。

---

## 4. 竖切路线图（终点不简陋的证据；竖切2+ 由 codex 实现，CC 审，用户验）

- **竖切1（本计划）**：封闭世界，`set_state`/`move`，确定性漂移，mock 决策。**产出：能跑、能看见世界自行变化的垂直管道。** ← CC 亲手写，黄金模板。
- **竖切2（开放世界，独立计划）**：新增 `create_object`/`destroy_object`，`gone_log`、`money` 预算、容量上限、类别白名单。物品有生有死、跨天因果链。
- **竖切3（接真实 LLM，独立计划）**：`world_llm_enabled=True` 分支接 GPT-4o-mini；prompt 注入房间/物品白名单防幻觉；mock 仍是 fallback 与测试路径。
- **竖切4（接线，独立计划）**：world tick 接入 `life_loop.py`/scheduler；world 摘要写入 `LifeState`（经现有桥梁、不碰红线）流向对话；轻 tick/重 tick 分档。
- **竖切5（跨天生命周期，独立计划）**：`daily_cycle.py` 取代 `_daily_reset_placeholder`；睡眠/醒来结算、未完成事务、residue 跨天、记忆加权检索。
- **竖切6（≥7 天连续模拟验收，独立计划）**：非重复性、因果连续、资源占用矩阵验收。

每根竖切独立可跑、独立验收，各自一份本格式的计划。

---

## 5. 自检结果

**规格覆盖度：** 封闭世界静态定义（任务1）、动态持久（任务2）、自行变化/漂移（任务3）、决策守门（任务4）、决策接口+mock（任务5）、肉眼验收（任务6）——本计划范围（封闭世界垂直管道）全覆盖。开放世界/真LLM/接线/跨天 明确划入竖切2-6 独立计划，非本计划范围。

**占位符扫描：** 已查无 TODO/待定/"后续实现"；每个代码步骤含完整可运行代码；`world_brain` 的 LLM 分支是**显式 raise**（受控未实现 + 路线图指明竖切3），非偷懒占位。

**类型一致性：** `WorldDef`/`WorldState`/`WorldOp`/`ActionPlan` 在任务1定义，任务2-6 引用一致；`validate_ops` 返回 `(accepted, rejected[(op,reason)])` 在任务4定义、任务6按此解包；`apply_drift` 返回 `(state, changed)` 在任务3定义、任务6按此解包。一致。

---

## 6. 执行交接

计划已归档到 `docs/archive/superpowers-plans/2026-06-07-living-world-slice1-closed.md`。

竖切1 由 **CC 内联执行**（亲手写黄金模板），不下放给 codex。建议方式：

- 使用 **superpowers:executing-plans** 在当前会话按任务1→6 顺序执行，每个任务后停下让用户肉眼对照验收契约。

竖切2 起，再用"合同片段 + 本模板代码"下放给 GPT-5.5/codex。

**执行前需用户确认两件事：** (1) 解除"不新增表"约束（仅 `life_world_state`）；(2) 家的规模就用 4 房间/15 物品默认，还是调整。
