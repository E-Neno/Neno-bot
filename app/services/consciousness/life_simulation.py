from __future__ import annotations

from pydantic import BaseModel

from .models import (
    ActivityEpisode,
    DailyIntent,
    MicroEvent,
    NenoState,
    VirtualSpace,
)


STRONG_RESIDUE_THRESHOLD = 0.7
LOW_ENERGY_THRESHOLD = 30.0
HIGH_NEED_THRESHOLD = 70.0


class SimulationDecision(BaseModel):
    action: str
    intent: DailyIntent
    activity_key: str
    activity_label: str
    space: VirtualSpace
    reason: str
    continuity_note: str = ""
    current_episode_id: int | None = None


class LifeSimulation:
    def decide(
        self,
        state: NenoState,
        current_episode: ActivityEpisode | None = None,
    ) -> SimulationDecision:
        intent = self._select_intent(state)
        activity_key, activity_label = _ACTIVITY_BY_INTENT[intent.key]
        space = _SPACE_BY_INTENT[intent.key]
        action = self._select_action(current_episode, activity_key, intent.key)
        return SimulationDecision(
            action=action,
            intent=intent,
            activity_key=activity_key,
            activity_label=activity_label,
            space=space,
            reason=self._decision_reason(action, intent, current_episode),
            continuity_note=self._continuity_note(
                state,
                action,
                activity_label,
            ),
            current_episode_id=current_episode.id if current_episode else None,
        )

    def derive_micro_event(
        self,
        state: NenoState,
        decision: SimulationDecision,
        target_episode: ActivityEpisode,
        *,
        previous_episode: ActivityEpisode | None = None,
    ) -> MicroEvent | None:
        if decision.action == "continue":
            return None

        primary_object = (
            decision.space.available_objects[0]
            if decision.space.available_objects
            else "nearby_object"
        )
        residue = state.life.residue
        residue_note = (
            f" The residue {residue.topic!r} remained present."
            if residue.topic
            else ""
        )

        if decision.action == "create":
            kind = "episode_started"
            content = (
                f"At {target_episode.place} during {target_episode.time_phase}, "
                f"Neno began {target_episode.activity_key} with {primary_object} "
                f"for the {decision.intent.key} intent.{residue_note}"
            )
        elif decision.action == "transition":
            kind = "episode_transition"
            previous_key = (
                previous_episode.activity_key
                if previous_episode is not None
                else "previous_activity"
            )
            content = (
                f"Neno moved from {previous_key} to "
                f"{target_episode.activity_key} at {target_episode.place}, "
                f"using {primary_object} for the {decision.intent.key} intent."
                f"{residue_note}"
            )
        elif decision.action == "interrupt":
            kind = "episode_interrupted"
            previous_key = (
                previous_episode.activity_key
                if previous_episode is not None
                else "previous_activity"
            )
            content = (
                f"Neno paused {previous_key} and moved to "
                f"{target_episode.activity_key} at {target_episode.place}, "
                f"reaching for {primary_object} to recover.{residue_note}"
            )
        else:
            return None

        return MicroEvent(
            trace_id=target_episode.trace_id or "",
            episode_id=target_episode.id,
            kind=kind,
            content=content,
            salience=0.6 if residue.topic else 0.45,
            metadata={
                "episode_id": target_episode.id,
                "daily_intent": decision.intent.key,
                "place": target_episode.place,
                "time_phase": target_episode.time_phase,
                "activity_key": target_episode.activity_key,
                "space_key": decision.space.key,
                "available_objects": list(decision.space.available_objects),
                "decision_action": decision.action,
            },
        )

    @staticmethod
    def _select_intent(state: NenoState) -> DailyIntent:
        residue = state.life.residue
        needs = state.life.need
        energy = state.energy.value
        phase = state.life.time_phase

        if residue.topic and residue.intensity >= STRONG_RESIDUE_THRESHOLD:
            return DailyIntent(
                key="process_memory",
                reason=(
                    f"strong residue {residue.topic!r} "
                    f"has intensity {residue.intensity:.2f}"
                ),
                drivers=["residue", "memory"],
            )
        if energy < LOW_ENERGY_THRESHOLD:
            return DailyIntent(
                key="recover",
                reason=f"energy {energy:.1f} is below recovery threshold",
                drivers=["energy"],
            )
        if needs.connection >= HIGH_NEED_THRESHOLD:
            return DailyIntent(
                key="seek_connection",
                reason=(
                    f"connection need {needs.connection:.1f} "
                    "is the strongest active need"
                ),
                drivers=["connection_need"],
            )
        if needs.order >= HIGH_NEED_THRESHOLD:
            return DailyIntent(
                key="organize",
                reason=f"order need {needs.order:.1f} favors structured activity",
                drivers=["order_need"],
            )
        if phase in {"early_morning", "forenoon", "afternoon"}:
            return DailyIntent(
                key="organize",
                reason=f"time phase {phase!r} favors a structured activity",
                drivers=["time_phase"],
            )
        return DailyIntent(
            key="observe",
            reason=f"time phase {phase!r} favors quiet observation",
            drivers=["time_phase"],
        )

    @staticmethod
    def _select_action(
        current_episode: ActivityEpisode | None,
        activity_key: str,
        intent_key: str,
    ) -> str:
        if current_episode is None or current_episode.status != "active":
            return "create"
        if current_episode.activity_key == activity_key:
            return "continue"
        if intent_key == "recover":
            return "interrupt"
        return "transition"

    @staticmethod
    def _decision_reason(
        action: str,
        intent: DailyIntent,
        current_episode: ActivityEpisode | None,
    ) -> str:
        if action == "create":
            return f"create episode because {intent.reason}"
        if action == "continue":
            return (
                f"continue episode {current_episode.id} because the target "
                f"activity is unchanged; {intent.reason}"
            )
        if action == "interrupt":
            return (
                f"interrupt episode {current_episode.id} because recovery "
                f"takes priority; {intent.reason}"
            )
        return (
            f"transition from episode {current_episode.id} because the target "
            f"activity changed; {intent.reason}"
        )

    @staticmethod
    def _continuity_note(
        state: NenoState,
        action: str,
        activity_label: str,
    ) -> str:
        residue = state.life.residue
        if residue.topic:
            return (
                f"{action} toward {activity_label}; residue "
                f"{residue.topic!r} remains at {residue.intensity:.2f}"
            )
        if state.life.activity_label:
            return (
                f"{action} toward {activity_label} after "
                f"{state.life.activity_label}"
            )
        return f"{action} toward {activity_label}"


_ACTIVITY_BY_INTENT = {
    "recover": ("quiet_rest", "Rest quietly"),
    "process_memory": ("memory_processing", "Process a lingering memory"),
    "seek_connection": ("holding_connection", "Hold space for connection"),
    "organize": ("desk_organizing", "Organize the nearby workspace"),
    "observe": ("quiet_observing", "Observe the surroundings quietly"),
}


_SPACE_BY_INTENT = {
    "recover": VirtualSpace(
        key="rest_corner",
        label="Rest corner",
        place="rest_corner",
        available_objects=["blanket", "water", "soft_light"],
    ),
    "process_memory": VirtualSpace(
        key="memory_desk",
        label="Memory desk",
        place="window_desk",
        available_objects=["notebook", "pen", "warm_drink"],
    ),
    "seek_connection": VirtualSpace(
        key="connection_seat",
        label="Connection seat",
        place="window_seat",
        available_objects=["phone", "notebook", "warm_drink"],
    ),
    "organize": VirtualSpace(
        key="work_desk",
        label="Work desk",
        place="work_desk",
        available_objects=["notebook", "storage_box", "pen"],
    ),
    "observe": VirtualSpace(
        key="quiet_window",
        label="Quiet window",
        place="window_seat",
        available_objects=["chair", "window", "warm_drink"],
    ),
}
