from app.services.consciousness.config import ConsciousnessConfig
from app.services.consciousness.world_model import load_world_def, seed_world_state
from app.services.consciousness.life_events import LifeEventSource, LifeEvent


class _RNG:
    """确定性 rng：每次 random() 返回固定值，便于精确测分支。"""
    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


class _N:
    class energy:
        value = 80.0
        status = "awake"


def _src():
    return LifeEventSource(ConsciousnessConfig())


def _setup(location="living_room"):
    wd = load_world_def()
    st = seed_world_state(wd)
    st.location = location
    return wd, st


def test_high_draw_emits_nothing():
    wd, st = _setup()
    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_N, phase="afternoon", rng=_RNG(0.9))
    assert ev is None


def test_mishap_breaks_drinkware_in_room():
    wd, st = _setup(location="kitchen")  # mug 在厨房
    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_N, phase="afternoon", rng=_RNG(0.02))
    assert isinstance(ev, LifeEvent)
    assert ev.kind == "mishap"
    assert ev.world_op is not None
    assert ev.world_op.op == "set_state" and ev.world_op.state == "broken"
    assert ev.mood_delta < 0


def test_memory_event_when_gone_log_nonempty():
    wd, st = _setup()
    st.gone_log = [{"object": "mug", "label": "马克杯", "cause": "broken", "when": "x"}]
    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_N, phase="afternoon", rng=_RNG(0.2))
    assert ev.kind == "memory"
    assert "马克杯" in ev.content
    assert ev.mood_delta < 0


def test_morning_emits_weather():
    wd, st = _setup()
    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_N, phase="morning", rng=_RNG(0.2))
    assert ev.kind == "weather"
    assert ev.world_op is not None


def test_low_energy_emits_craving():
    wd, st = _setup()

    class _Low:
        class energy:
            value = 30.0
            status = "awake"

    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_Low, phase="afternoon", rng=_RNG(0.2))
    assert ev.kind == "craving"


def test_default_emits_message():
    wd, st = _setup()
    ev = _src().maybe_emit(world_def=wd, world_state=st, nstate=_N, phase="afternoon", rng=_RNG(0.2))
    assert ev.kind == "message"
    assert ev.world_op is not None
    assert ev.world_op.object == "phone" and ev.world_op.state == "has_unread"
    assert ev.mood_delta > 0
