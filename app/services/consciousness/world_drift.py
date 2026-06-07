from __future__ import annotations

from .config import ConsciousnessConfig
from .world_model import WorldDef, WorldState


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
