"""Living World 竖切1 dry-run 验收脚本。

跑一轮：漂移 → 读世界 → mock决策 → 逐条校验+执行 → 落账 → 打印。
不调真实模型。运行：python scripts/world_slice1_dryrun.py
"""
from __future__ import annotations

import asyncio

from app.storage.db import init_db
from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import apply_op, load_world_def, WorldOp
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
    print(
        f"kettle={state.object_states.get('kettle')} "
        f"plants={state.object_states.get('plants')}"
    )

    # 模拟距上次 45 分钟：水壶若 warm 会凉
    state.object_states.setdefault("kettle", "warm")
    if state.object_states["kettle"] == "cold":
        state.object_states["kettle"] = "warm"  # 制造可观测漂移
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
    bad = WorldOp(op="set_state", object="dragon", state="boiling")
    _, rej = validate_ops(wd, state, [bad])
    print(f"  REJECT(故意) set_state dragon ({rej[0][1]}) —— 世界未变")

    await store.write(state)
    after = await store.read()
    print("\n=== 落账后世界（持久）===")
    print(f"location={after.location}")
    print(
        f"kettle={after.object_states.get('kettle')} "
        f"book={after.object_states.get('book')}"
    )
    print("\n再次运行本脚本，应看到状态从这里接着变（持久性验收）。")


if __name__ == "__main__":
    asyncio.run(main())
