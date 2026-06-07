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
    assert out.object_states["kettle"] == "cold"  # 已冷不再变


def test_fresh_plant_needs_water_after_two_days():
    wd, st, cfg = _setup()
    out, changed = apply_drift(wd, st, elapsed_minutes=2881, config=cfg)
    assert out.object_states["plants"] == "needs_water"
