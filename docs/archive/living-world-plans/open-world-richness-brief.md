# 世界扩容 — Codex 交接 Brief（每间房 ~20 物）

> 纯数据驱动加法，延续刀②风格。目标：现在每间房物品太少（家内 5-9 个），
> 扩到**每个家内房间 ~18-22 个物品**、外部场所 ~8-12 个，让世界丰满、她有更多可活的东西。

## 红线（违反即作废）
1. **不改决策机制**：不动 world_brain.py、world_pressure.py 的 should_wake/accumulate/on_wake、
   world_loop.py 的 tick 三分支与滑行逻辑。
2. **不绕 action_validator**：新物品 category 必须在 categories 里、状态合法。
3. 不碰 .env，不要 git commit/push，不改 agents/openai.yaml。
4. 不要读 ~/.claude/ 或 .claude/skills/ 下的文件。
5. 加法不改乘法：只加数据，不引入新紧耦合反馈。

## 要改的文件（4 处）

### A. `app/services/consciousness/virtual_world.json`（主要工作）
- 每个**家内房间**（bedroom/kitchen/living_room/balcony）扩到 **18-22 个物品**；
  每个**外部场所**（entryway/building_entrance/convenience_store/cafe/park）扩到 **8-12 个**。
- 复用现有 categories；不够就加新 category（连同合法 states + default）。已有 category：
  drinkware/appliance/furniture/plant/device/book/window/light/media/textile/pantry/
  household/decor/rack/fixture/nature。
- 约束：
  - 每个新 object 有 `category`（categories 里有）和中文 `label`。
  - object key 用英文小写下划线，全局唯一；label 用中文。
  - 每个新 object 必须挂进某 room 的 `objects` 数组。
  - **不要删现有物品**（gone_log/removed/测试/slot 都引用现有 key）。
  - **不要动 `adjacency` 和 `outside` 两个字段**（刀③的，保持原样）。
- 物品要符合房间语义（厨房放锅碗瓢盆调料、卧室放衣物书桌摆件、客厅放影音书籍绿植、
  阳台放园艺杂物、咖啡馆放杯具桌椅、便利店放货架商品、公园放长椅设施）。

### B. `app/services/consciousness/world_loop.py` 的 `OBJ_EMOJI`
- 给**每个新增 object key** 加一个贴切的 emoji（前端反应层据此占位渲染）。漏了会显示空白。

### C. `app/services/consciousness/action_validator.py`
- `ROOM_CAP = 15` → 抬到 **30**（否则房间静态物品超 15 后，她 create_object 永远 room_full）。

### D. 不需要碰 life_events / world_pressure
- 本次只加物品，不加新 LifeEvent.kind，所以 salience 表不用动。**别加新事件种类**（保持简单）。

## 测试（先验后改 / 改完必跑）
- `load_world_def()` 不抛、`seed_world_state()` 给所有新物品取到默认态。
- 已有测试全绿：`python -m pytest tests/unit/test_world_model.py tests/unit/test_action_validator.py
  tests/unit/test_world_brain.py tests/unit/test_world_open.py tests/unit/test_world_drift.py -q`
- 可加一个测试：每个家内房间 objects 数 >= 15。
- **已知预存在 flaky**（别管别修）：`test_world_loop.py::test_glide_falls_back_on_transient_action`
  无种子 rng ~5-8% 概率挂。

## 验收（codex 自查）
1. 上面测试全绿。
2. `load_world_def()` 能 load；grep 确认每个新 object 都在 OBJ_EMOJI 里有 emoji。
3. ROOM_CAP=30。没动 adjacency/outside/world_brain/should_wake/.env（git diff 自查）。
4. 不 commit；报 diff 摘要 + 测试输出 + 每间房最终物品数。
