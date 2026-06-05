from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.db import add_debug_event

from .config import ConsciousnessConfig
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .models import LifeState, StateMutation
from .state_store import StateStore


class LifeLoop:
    def __init__(
        self,
        state_store: StateStore,
        recorder: ExperienceRecorder,
        config: ConsciousnessConfig,
    ) -> None:
        self._state_store = state_store
        self._recorder = recorder
        self._config = config

    async def dry_run(self, trace_id: str | None = None) -> dict[str, Any]:
        state = await self._state_store.read()
        recent_unspoken = await self._recorder.list_recent(limit=20, status="unspoken")

        if state.energy.status == "sleeping":
            return {
                "success": True,
                "enabled": self._config.life_loop_enabled,
                "action": "skipped_sleeping",
                "reason": "energy_sleeping",
                "would_update_life": state.life.model_dump(),
                "would_record_experience": None,
                "would_mutate_state": None,
            }

        life = self._decide_life_state(state, recent_unspoken)
        experience = {
            "trace_id": trace_id or "",
            "source": "life_loop",
            "kind": "state_shift",
            "content": f"Neno {life.current_activity}",
            "mood_impact": 0.0,
            "desire_impact": 0.0,
            "salience": 0.4,
            "expression_status": "unspoken",
            "metadata": {
                "life": life.model_dump(),
                "reason": "life_loop_tick",
            },
        }

        return {
            "success": True,
            "enabled": self._config.life_loop_enabled,
            "action": "would_update",
            "would_update_life": life.model_dump(),
            "would_record_experience": experience,
            "would_mutate_state": {
                "mood_valence_delta": 0.0,
                "desire_pulse": 0.0,
            },
        }

    async def run_once(self, trace_id: str | None = None) -> dict[str, Any]:
        if not self._config.life_loop_enabled:
            return {
                "success": True,
                "enabled": False,
                "action": "disabled",
            }

        try:
            plan = await self.dry_run(trace_id)
            if plan.get("action") == "skipped_sleeping":
                return plan

            life = LifeState.model_validate(plan["would_update_life"])
            exp_data = plan["would_record_experience"]
            experience_id = await self._recorder.record(
                InnerExperienceIn(
                    trace_id=exp_data["trace_id"],
                    source=exp_data["source"],
                    kind=exp_data["kind"],
                    content=exp_data["content"],
                    mood_impact=exp_data["mood_impact"],
                    desire_impact=exp_data["desire_impact"],
                    salience=exp_data["salience"],
                    expression_status=exp_data["expression_status"],
                    metadata=exp_data["metadata"],
                )
            )
            await self._state_store.submit_mutation(
                StateMutation(
                    life=life,
                    mood_valence_delta=plan["would_mutate_state"]["mood_valence_delta"],
                    desire_pulse=plan["would_mutate_state"]["desire_pulse"],
                    trace_id=trace_id or "",
                    reason="life_loop",
                )
            )
            return {
                "success": True,
                "enabled": True,
                "action": "updated",
                "experience_id": experience_id,
                "life": life.model_dump(),
            }
        except Exception as exc:
            add_debug_event(
                trace_id=trace_id,
                module="life_loop",
                event="run_failed",
                level="warning",
                success=False,
                reason=str(exc),
                metadata_json=json.dumps({"trace_id": trace_id}, ensure_ascii=False),
            )
            return {
                "success": False,
                "enabled": True,
                "action": "error",
                "reason": str(exc),
            }

    def _decide_life_state(self, state: Any, recent_unspoken: list[dict[str, Any]]) -> LifeState:
        now = datetime.now(timezone.utc).isoformat()
        if state.energy.value < 30:
            return LifeState(
                mode="resting",
                attention="self",
                current_activity="low_energy_resting",
                last_transition_at=now,
                residue=state.life.residue,
            )

        if state.desire.value >= self._config.desire_threshold and state.last_interaction.user_id:
            return LifeState(
                mode="seeking_connection",
                attention="user",
                current_activity="thinking_of_user",
                last_transition_at=now,
                residue=state.life.residue,
            )

        if _has_recent_unspoken(recent_unspoken):
            return LifeState(
                mode="absorbed",
                attention="memory",
                current_activity="carrying_unspoken_thought",
                last_transition_at=now,
                residue=state.life.residue,
            )

        return LifeState(
            mode="idle",
            attention="ambient",
            current_activity="quiet_observing",
            last_transition_at=now,
            residue=state.life.residue,
        )


def _has_recent_unspoken(rows: list[dict[str, Any]]) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    for row in rows:
        created_at = row.get("created_at")
        if not isinstance(created_at, str):
            continue
        try:
            parsed = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed >= cutoff:
            return True
    return False
