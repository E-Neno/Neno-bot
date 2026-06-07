from __future__ import annotations

from app.services.consciousness.models import (
    ActivityEpisode,
    LifeResidue,
    LifeState,
    MicroEvent,
    NenoState,
    NeedState,
)


def _simulation():
    from app.services.consciousness.life_simulation import LifeSimulation

    return LifeSimulation()


def _state(
    *,
    energy: float = 70.0,
    time_phase: str = "afternoon",
    connection: float = 20.0,
    order: float = 20.0,
    residue_topic: str = "",
    residue_intensity: float = 0.0,
) -> NenoState:
    state = NenoState()
    state.energy.value = energy
    state.life.time_phase = time_phase
    state.life.need = NeedState(connection=connection, order=order)
    state.life.residue = LifeResidue(
        topic=residue_topic,
        mood="quiet",
        intensity=residue_intensity,
    )
    return state


def _episode(
    *,
    activity_key: str,
    episode_id: int = 7,
    place: str = "quiet_room",
) -> ActivityEpisode:
    return ActivityEpisode(
        id=episode_id,
        trace_id="trace-current",
        activity_key=activity_key,
        activity_label=activity_key.replace("_", " "),
        place=place,
        time_phase="afternoon",
        status="active",
        started_at="2026-06-06T06:00:00+00:00",
        updated_at="2026-06-06T06:30:00+00:00",
    )


def test_old_life_state_json_gets_episode_defaults():
    life = LifeState.model_validate(
        {
            "mode": "idle",
            "attention": "ambient",
            "current_activity": "quiet_observing",
        }
    )

    assert life.active_episode_id is None
    assert life.daily_intent == ""


def test_high_residue_selects_process_memory():
    decision = _simulation().decide(
        _state(
            energy=80,
            residue_topic="unfinished conversation",
            residue_intensity=0.85,
        )
    )

    assert decision.intent.key == "process_memory"
    assert decision.activity_key == "memory_processing"
    assert "residue" in decision.reason


def test_low_energy_selects_recover():
    decision = _simulation().decide(_state(energy=20))

    assert decision.intent.key == "recover"
    assert decision.activity_key == "quiet_rest"
    assert "energy" in decision.reason


def test_high_connection_need_selects_seek_connection():
    decision = _simulation().decide(_state(connection=85))

    assert decision.intent.key == "seek_connection"
    assert decision.activity_key == "holding_connection"
    assert "connection" in decision.reason


def test_default_time_phase_selects_observe_or_organize():
    simulation = _simulation()

    morning = simulation.decide(_state(time_phase="forenoon"))
    evening = simulation.decide(_state(time_phase="evening"))

    assert morning.intent.key == "organize"
    assert evening.intent.key == "observe"


def test_same_conditions_continue_current_episode():
    state = _state(time_phase="evening")
    current = _episode(activity_key="quiet_observing")

    decision = _simulation().decide(state, current)

    assert decision.action == "continue"
    assert decision.current_episode_id == current.id
    assert "continue" in decision.reason


def test_clear_condition_change_transitions_episode():
    state = _state(
        energy=75,
        residue_topic="unfinished conversation",
        residue_intensity=0.9,
    )
    current = _episode(activity_key="quiet_observing")

    decision = _simulation().decide(state, current)

    assert decision.action == "transition"
    assert decision.activity_key == "memory_processing"
    assert decision.current_episode_id == current.id


def test_low_energy_interrupts_non_rest_episode():
    current = _episode(activity_key="desk_organizing")

    decision = _simulation().decide(_state(energy=15), current)

    assert decision.action == "interrupt"
    assert decision.activity_key == "quiet_rest"
    assert "interrupt" in decision.reason


def test_virtual_space_matches_intent_and_activity():
    simulation = _simulation()

    recover = simulation.decide(_state(energy=10))
    organize = simulation.decide(_state(order=90))

    assert recover.space.place == "rest_corner"
    assert {"blanket", "water"} <= set(recover.space.available_objects)
    assert organize.space.place == "work_desk"
    assert "notebook" in organize.space.available_objects


def test_micro_event_json_roundtrip():
    event = MicroEvent(
        kind="noticed_detail",
        content="The room became quieter after the rain.",
        salience=0.45,
        metadata={
            "episode_id": 7,
            "daily_intent": "observe",
            "place": "window_seat",
        },
    )

    restored = MicroEvent.model_validate_json(event.model_dump_json())

    assert restored == event
    assert restored.metadata["episode_id"] == 7


def test_same_input_produces_identical_decision():
    simulation = _simulation()
    state = _state(
        energy=72,
        time_phase="night",
        connection=25,
        order=25,
        residue_topic="small unfinished thought",
        residue_intensity=0.2,
    )
    current = _episode(activity_key="quiet_observing")

    first = simulation.decide(state, current)
    second = simulation.decide(state, current)

    assert first.model_dump() == second.model_dump()


def _target_episode(decision, *, episode_id: int = 19) -> ActivityEpisode:
    return ActivityEpisode(
        id=episode_id,
        trace_id="trace-target",
        activity_key=decision.activity_key,
        activity_label=decision.activity_label,
        place=decision.space.place,
        time_phase="evening",
        status="active",
        started_at="2026-06-06T10:00:00+00:00",
        updated_at="2026-06-06T10:00:00+00:00",
        reason=decision.reason,
        continuity_note=decision.continuity_note,
    )


def test_create_derives_micro_event_from_target_episode_and_space():
    simulation = _simulation()
    state = _state(time_phase="evening")
    decision = simulation.decide(state)

    event = simulation.derive_micro_event(
        state,
        decision,
        _target_episode(decision),
    )

    assert event is not None
    assert event.kind == "episode_started"
    assert event.episode_id == 19
    assert decision.space.place in event.content
    assert decision.space.available_objects[0] in event.content
    assert event.metadata["daily_intent"] == decision.intent.key
    assert event.metadata["activity_key"] == decision.activity_key
    assert event.metadata["space_key"] == decision.space.key


def test_transition_derives_micro_event():
    simulation = _simulation()
    state = _state(
        residue_topic="unfinished conversation",
        residue_intensity=0.9,
    )
    current = _episode(activity_key="quiet_observing")
    decision = simulation.decide(state, current)

    event = simulation.derive_micro_event(
        state,
        decision,
        _target_episode(decision),
        previous_episode=current,
    )

    assert event is not None
    assert event.kind == "episode_transition"
    assert "unfinished conversation" in event.content
    assert current.activity_key in event.content
    assert decision.activity_key in event.content


def test_interrupt_derives_micro_event():
    simulation = _simulation()
    state = _state(energy=15, time_phase="night")
    current = _episode(activity_key="desk_organizing")
    decision = simulation.decide(state, current)

    event = simulation.derive_micro_event(
        state,
        decision,
        _target_episode(decision),
        previous_episode=current,
    )

    assert event is not None
    assert event.kind == "episode_interrupted"
    assert current.activity_key in event.content
    assert decision.space.place in event.content


def test_stable_continue_does_not_derive_duplicate_micro_event():
    simulation = _simulation()
    state = _state(time_phase="evening")
    current = _episode(activity_key="quiet_observing")
    decision = simulation.decide(state, current)

    event = simulation.derive_micro_event(state, decision, current)

    assert decision.action == "continue"
    assert event is None


def test_same_micro_event_input_is_deterministic():
    simulation = _simulation()
    state = _state(
        residue_topic="small unfinished thought",
        residue_intensity=0.8,
    )
    decision = simulation.decide(
        state,
        _episode(activity_key="quiet_observing"),
    )
    target = _target_episode(decision)

    first = simulation.derive_micro_event(state, decision, target)
    second = simulation.derive_micro_event(state, decision, target)

    assert first is not None
    assert first.model_dump() == second.model_dump()
