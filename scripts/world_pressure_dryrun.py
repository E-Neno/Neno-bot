"""world_pressure dry-run 模拟脚本（诚实版）。

模型与生产一致：每 tick = REAL_SECONDS_PER_TICK 真实秒，同时 sim 时间前进
SIM_SECONDS_PER_TICK。min_gap / budget 用真实时钟（成本护栏），sim 时钟仅用于
"她活了多久"的展示。运行足够久以跨越多个预算小时，从而真实体现唤醒节奏。

只打印"唤醒"事件（否则上千行），并在结尾给出两个时钟下的频率，帮助判断：
她在真实时间里多久真思考一次（≈ 成本），在她自己的生活里多久真思考一次（≈ 体验）。

纯本地，不调任何网络/模型。
用法：python scripts/world_pressure_dryrun.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_pressure import (
    PressureState,
    accumulate,
    is_hard,
    on_wake,
    should_wake,
)

# ── 参数 ─────────────────────────────────────────────────────
SEED = 42
REAL_SECONDS_PER_TICK = 8        # 生产：8 秒一 tick
SIM_SECONDS_PER_TICK = 30 * 60   # 生产：每 tick sim 前进 30 分钟
SIM_REAL_RATIO = SIM_SECONDS_PER_TICK / REAL_SECONDS_PER_TICK  # 225x
START_SIM_TIME = 8 * 3600        # sim 从 08:00 起
REAL_HOURS = 4                   # 模拟 4 个真实小时（跨多个预算小时）
TOTAL_TICKS = int(REAL_HOURS * 3600 / REAL_SECONDS_PER_TICK)

EVENT_POOL: list[tuple[float, list[str]]] = [
    (0.55, []),
    (0.70, ["action_done"]),
    (0.80, ["phase_change"]),
    (0.88, ["plant_thirsty"]),
    (0.93, ["action_done", "phase_change"]),
    (0.96, ["message_in"]),
    (0.98, ["money_low"]),
    (1.00, ["kettle_broken"]),
]


def pick_events(rng: random.Random) -> list[str]:
    r = rng.random()
    for threshold, kinds in EVENT_POOL:
        if r < threshold:
            return kinds
    return []


def fmt_clock(seconds: float) -> str:
    total = int(seconds) % (24 * 3600)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"


def main() -> None:
    rng = random.Random(SEED)
    config = ConsciousnessConfig()
    state = PressureState()

    total_wakes = 0
    wake_reasons: dict[str, int] = {}
    real_gaps_s: list[float] = []
    last_wake_real: float | None = None
    wakes_per_real_hour: dict[int, int] = {}

    print(f"参数: tick={REAL_SECONDS_PER_TICK}s 真实 / +{SIM_SECONDS_PER_TICK//60}min sim "
          f"(sim 快 {SIM_REAL_RATIO:.0f}x) · 阈值={config.world_pressure_threshold} "
          f"min_gap={config.world_wake_min_gap_seconds}s 预算={config.world_wake_budget_per_hour}/真实小时")
    print(f"模拟 {REAL_HOURS} 真实小时 = {TOTAL_TICKS} ticks = "
          f"{TOTAL_TICKS*SIM_SECONDS_PER_TICK/86400:.1f} sim 天\n")
    print(f"{'tick':>5}  {'真实':>6}  {'sim时钟':>7}  {'sim第N天':>7}  {'触发事件':<24}  {'原因':<10}")
    print("-" * 80)

    for tick in range(TOTAL_TICKS):
        real_now = tick * REAL_SECONDS_PER_TICK
        sim_now = START_SIM_TIME + tick * SIM_SECONDS_PER_TICK

        events = pick_events(rng)
        hard = is_hard(events, config)
        state = accumulate(state, events, config, now=real_now)
        wake, reason = should_wake(state, config, now=real_now, hard_event=hard)

        if wake:
            state = on_wake(state, now=real_now)
            total_wakes += 1
            wake_reasons[reason] = wake_reasons.get(reason, 0) + 1
            if last_wake_real is not None:
                real_gaps_s.append(real_now - last_wake_real)
            last_wake_real = real_now
            rh = int(real_now // 3600)
            wakes_per_real_hour[rh] = wakes_per_real_hour.get(rh, 0) + 1
            sim_day = int(tick * SIM_SECONDS_PER_TICK // 86400) + 1
            ev = ",".join(events) if events else "(无事件/压力到顶)"
            print(f"{tick:>5}  {fmt_clock(real_now):>6}  {fmt_clock(sim_now):>7}  "
                  f"{'第'+str(sim_day)+'天':>7}  {ev:<24}  {reason:<10}")

    # ── 统计 ────────────────────────────────────────────────
    sim_days = TOTAL_TICKS * SIM_SECONDS_PER_TICK / 86400
    print("\n" + "=" * 80)
    print("统计")
    print("=" * 80)
    print(f"真实时长:           {REAL_HOURS} 小时   |   她活过的 sim 时长: {sim_days:.1f} 天")
    print(f"总唤醒(真思考)次数: {total_wakes}")
    print(f"  → 每真实小时:     {total_wakes/REAL_HOURS:.1f} 次   (成本 ≈ 这个 × 单价)")
    print(f"  → 每 sim 天:       {total_wakes/sim_days:.2f} 次   (她生活里多久真想一次)")
    if real_gaps_s:
        avg = sum(real_gaps_s) / len(real_gaps_s)
        print(f"平均真实间隔:       {avg:.0f}s ({avg/60:.1f} 分钟)")
    print("各原因:")
    for reason, count in sorted(wake_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:<12} {count}")
    print("每真实小时唤醒数(看预算护栏是否生效):")
    for h in sorted(wakes_per_real_hour):
        print(f"  第{h+1}真实小时: {wakes_per_real_hour[h]} 次")


if __name__ == "__main__":
    main()
