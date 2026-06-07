from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.db import add_debug_event

from .activity_episode_store import ActivityEpisodeStore
from .config import ConsciousnessConfig
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .life_simulation import LifeSimulation, SimulationDecision
from .models import (
    ActivityEpisode,
    LifeEnvironment,
    LifeState,
    MicroEvent,
    StateMutation,
)
from .state_store import StateStore


class LifeLoop:
    def __init__(
        self,
        state_store: StateStore,
        recorder: ExperienceRecorder,
        config: ConsciousnessConfig,
        simulation: LifeSimulation | None = None,
        episode_store: ActivityEpisodeStore | None = None,
    ) -> None:
        self._state_store = state_store
        self._recorder = recorder
        self._config = config
        self._simulation = simulation or LifeSimulation()
        self._episode_store = episode_store or ActivityEpisodeStore()

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
                "micro_event_preview": None,
            }

        persisted_life = state.life.model_copy(deep=True)
        life = self._decide_life_state(state, recent_unspoken)
        episode_decision = None
        current_episode = None
        episode_error = None
        micro_event_preview = None
        try:
            current_episode_data = await self._episode_store.get_active_episode()
            if current_episode_data is not None:
                current_episode = ActivityEpisode.model_validate(current_episode_data)
            simulation_state = state.model_copy(deep=True)
            simulation_state.life = life
            decision = self._simulation.decide(simulation_state, current_episode)
            episode_decision = decision.model_dump()
            preview_episode_id = (
                current_episode.id
                if decision.action == "continue" and current_episode is not None
                else None
            )
            self._sync_life_with_decision(
                life,
                decision,
                active_episode_id=preview_episode_id,
            )
            target_episode = self._episode_from_decision(
                decision,
                episode_id=preview_episode_id,
                trace_id=trace_id,
                time_phase=life.time_phase,
            )
            preview = self._simulation.derive_micro_event(
                simulation_state,
                decision,
                target_episode,
                previous_episode=current_episode,
            )
            if preview is not None:
                micro_event_preview = preview.model_dump()
        except Exception as exc:
            episode_error = str(exc)
            life = self._life_for_current_episode(
                persisted_life,
                current_episode,
            )

        experience = (
            self._failure_experience(
                trace_id=trace_id,
                life=life,
                episode_error=episode_error,
                attempted_decision=episode_decision,
            )
            if episode_error is not None
            else self._micro_event_experience(micro_event_preview)
        )

        result = {
            "success": True,
            "enabled": self._config.life_loop_enabled,
            "action": "would_update",
            "would_update_life": life.model_dump(),
            "would_record_experience": experience,
            "would_mutate_state": {
                "mood_valence_delta": 0.0,
                "desire_pulse": 0.0,
            },
            "episode_decision": episode_decision,
            "micro_event_preview": micro_event_preview,
            "current_episode": (
                current_episode.model_dump() if current_episode is not None else None
            ),
            "persisted_life": persisted_life.model_dump(),
        }
        if episode_error is not None:
            result["episode_error"] = episode_error
        return result

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
            persisted_life = LifeState.model_validate(plan["persisted_life"])
            current_episode_data = plan.get("current_episode")
            current_episode = (
                ActivityEpisode.model_validate(current_episode_data)
                if current_episode_data is not None
                else None
            )
            episode_error = plan.get("episode_error")
            episode_decision_data = plan.get("episode_decision")
            micro_event_data = plan.get("micro_event_preview")
            active_episode_id = None
            if episode_decision_data is not None:
                try:
                    decision = SimulationDecision.model_validate(
                        episode_decision_data
                    )
                    active_episode_id = await self._apply_episode_decision(
                        decision,
                        trace_id=trace_id,
                        time_phase=life.time_phase,
                    )
                    self._sync_life_with_decision(
                        life,
                        decision,
                        active_episode_id=active_episode_id,
                    )
                except Exception as exc:
                    episode_error = str(exc)
                    life = self._life_for_current_episode(
                        persisted_life,
                        current_episode,
                    )

            experience_id = None
            if episode_error is not None:
                exp_data = self._failure_experience(
                    trace_id=trace_id,
                    life=life,
                    episode_error=episode_error,
                    attempted_decision=episode_decision_data,
                )
            elif micro_event_data is not None:
                event = MicroEvent.model_validate(micro_event_data)
                event.episode_id = active_episode_id
                event.metadata["episode_id"] = active_episode_id
                exp_data = self._micro_event_experience(event.model_dump())
                exp_data["metadata"]["life"] = life.model_dump()
            else:
                exp_data = None

            if exp_data is not None:
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
            result = {
                "success": True,
                "enabled": True,
                "action": "updated",
                "experience_id": experience_id,
                "life": life.model_dump(),
                "episode_decision": episode_decision_data,
            }
            if episode_error is not None:
                result["episode_error"] = episode_error
            return result
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

    async def _apply_episode_decision(
        self,
        decision: SimulationDecision,
        *,
        trace_id: str | None,
        time_phase: str,
    ) -> int:
        current_id = decision.current_episode_id
        if decision.action == "continue":
            if current_id is None:
                raise ValueError("continue decision requires current episode")
            updated = await self._episode_store.continue_episode(
                current_id,
                activity_label=decision.activity_label,
                place=decision.space.place,
                time_phase=time_phase,
                reason=decision.reason,
                continuity_note=decision.continuity_note,
                metadata=self._episode_metadata(decision),
            )
            if updated is None:
                raise RuntimeError("active episode disappeared before continue")
            return int(updated["id"])

        if decision.action == "transition":
            if current_id is None:
                raise ValueError("transition decision requires current episode")
            previous_status = "ended"
        elif decision.action == "interrupt":
            if current_id is None:
                raise ValueError("interrupt decision requires current episode")
            previous_status = "interrupted"
        elif decision.action != "create":
            raise ValueError(f"unsupported episode action: {decision.action}")
        else:
            previous_status = None

        episode_data = {
            "trace_id": trace_id,
            "activity_key": decision.activity_key,
            "activity_label": decision.activity_label,
            "place": decision.space.place,
            "time_phase": time_phase,
            "reason": decision.reason,
            "continuity_note": decision.continuity_note,
            "metadata": self._episode_metadata(decision),
        }
        if previous_status is not None:
            return await self._episode_store.replace_active_episode(
                current_id,
                previous_status=previous_status,
                **episode_data,
            )
        return await self._episode_store.start_episode(
            **episode_data,
        )

    @staticmethod
    def _sync_life_with_decision(
        life: LifeState,
        decision: SimulationDecision,
        *,
        active_episode_id: int | None,
    ) -> None:
        life.current_activity = decision.activity_key
        life.activity_label = decision.activity_label
        life.activity_reason = decision.reason
        life.continuity_note = decision.continuity_note
        life.place = decision.space.place
        life.active_episode_id = active_episode_id
        life.daily_intent = decision.intent.key

    @staticmethod
    def _life_for_current_episode(
        persisted_life: LifeState,
        current_episode: ActivityEpisode | None,
    ) -> LifeState:
        life = persisted_life.model_copy(deep=True)
        if current_episode is None:
            return life
        life.active_episode_id = current_episode.id
        life.current_activity = current_episode.activity_key
        life.activity_label = current_episode.activity_label
        life.place = current_episode.place
        life.activity_reason = current_episode.reason
        life.continuity_note = current_episode.continuity_note
        return life

    @staticmethod
    def _episode_metadata(decision: SimulationDecision) -> dict[str, Any]:
        return {
            "daily_intent": decision.intent.key,
            "decision_action": decision.action,
            "space_key": decision.space.key,
            "available_objects": decision.space.available_objects,
        }

    @staticmethod
    def _episode_from_decision(
        decision: SimulationDecision,
        *,
        episode_id: int | None,
        trace_id: str | None,
        time_phase: str,
    ) -> ActivityEpisode:
        return ActivityEpisode(
            id=episode_id,
            trace_id=trace_id,
            activity_key=decision.activity_key,
            activity_label=decision.activity_label,
            place=decision.space.place,
            time_phase=time_phase,
            status="active",
            started_at="",
            updated_at="",
            reason=decision.reason,
            continuity_note=decision.continuity_note,
        )

    @staticmethod
    def _micro_event_experience(
        event_data: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if event_data is None:
            return None
        event = MicroEvent.model_validate(event_data)
        return {
            "trace_id": event.trace_id,
            "source": "life_simulation",
            "kind": event.kind,
            "content": event.content,
            "mood_impact": event.mood_impact,
            "desire_impact": event.desire_impact,
            "salience": event.salience,
            "expression_status": "unspoken",
            "metadata": dict(event.metadata),
        }

    @staticmethod
    def _failure_experience(
        *,
        trace_id: str | None,
        life: LifeState,
        episode_error: str,
        attempted_decision: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "trace_id": trace_id or "",
            "source": "life_loop",
            "kind": "episode_apply_failed",
            "content": f"Life episode attempt failed: {episode_error}",
            "mood_impact": 0.0,
            "desire_impact": 0.0,
            "salience": 0.1,
            "expression_status": "unspoken",
            "metadata": {
                "life": life.model_dump(),
                "episode_error": episode_error,
                "attempted_decision": attempted_decision,
            },
        }

    def _decide_life_state(self, state: Any, recent_unspoken: list[dict[str, Any]]) -> LifeState:
        return self._build_next_life_state(
            state, recent_unspoken, datetime.now(timezone.utc)
        )

    def _build_next_life_state(
        self, state: Any, recent_unspoken: list[dict[str, Any]], now: datetime
    ) -> LifeState:
        """根据当前状态、需求、residue、时间段，确定性地生成生活化的 LifeState 富字段。

        纯规则、无 LLM、无副作用。输出描述"她此刻在虚拟生活里正在做什么、为什么"。
        """
        iso = now.isoformat()
        phase = _time_phase(now)
        env = LifeEnvironment(summary=_ENV_BY_PHASE.get(phase, "安静的房间"))
        residue = state.life.residue
        continuity = self._continuity_note(state)

        if state.energy.value < 30:
            return LifeState(
                mode="resting",
                attention="self",
                current_activity="low_energy_resting",
                last_transition_at=iso,
                residue=residue,
                place="bed",
                time_phase=phase,
                environment=env,
                activity_label="靠着歇一会儿",
                activity_reason=f"精力只剩 {state.energy.value:.0f}，先放空歇会儿",
                continuity_note=continuity,
            )

        if residue.topic and residue.intensity >= _RESIDUE_STRONG_THRESHOLD:
            # 昨天反思留下的强余波，真正改变今天的推进，而不只是 continuity 引用
            return LifeState(
                mode="absorbed",
                attention="memory",
                current_activity="dwelling_on_residue",
                last_transition_at=iso,
                residue=residue,
                place="home_desk",
                time_phase=phase,
                environment=env,
                activity_label=f"还在想{residue.topic}",
                activity_reason=(
                    f"昨天留下的{residue.mood or '那点情绪'}还没散，"
                    f"{residue.topic}一直搁在心里"
                ),
                continuity_note=continuity,
            )

        if state.desire.value >= self._config.desire_threshold and state.last_interaction.user_id:
            who = state.last_interaction.user_name or "对方"
            return LifeState(
                mode="seeking_connection",
                attention="user",
                current_activity="thinking_of_user",
                last_transition_at=iso,
                residue=residue,
                place="home_desk",
                time_phase=phase,
                environment=env,
                activity_label="有点想找人说说话",
                activity_reason=f"表达欲上来了，惦记着{who}",
                continuity_note=continuity,
            )

        if _has_recent_unspoken(recent_unspoken):
            return LifeState(
                mode="absorbed",
                attention="memory",
                current_activity="carrying_unspoken_thought",
                last_transition_at=iso,
                residue=residue,
                place="home_desk",
                time_phase=phase,
                environment=env,
                activity_label="回味没说出口的念头",
                activity_reason="有件事一直没说出口，心里还搁着",
                continuity_note=continuity,
            )

        return LifeState(
            mode="idle",
            attention="ambient",
            current_activity="quiet_observing",
            last_transition_at=iso,
            residue=residue,
            place="quiet_room",
            time_phase=phase,
            environment=env,
            activity_label="安静地看着四周",
            activity_reason="没有新的外部刺激，维持低强度观察",
            continuity_note=continuity,
        )

    @staticmethod
    def _continuity_note(state: Any) -> str:
        """串联上一片段：优先引用 residue 话题，其次引用上一次 activity_label。"""
        residue = state.life.residue
        if residue.topic:
            return f"还惦记着：{residue.topic}"
        prev = state.life.activity_label
        if prev:
            return f"接着刚才{prev}"
        return f"延续上一会儿的{state.life.current_activity}"


def _has_recent_unspoken(rows: list[dict[str, Any]]) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    for row in rows:
        # 生活模拟事件和失败观测都不是"没说出口的想法"，不能触发 absorbed。
        # 只有真正的内在想法（如 brain_judge）才参与该判断。
        if row.get("source") in {"life_loop", "life_simulation"}:
            continue
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


# residue.intensity 达到此阈值时，余波会改变下一次推进；低于则只作为 continuity 引用。
_RESIDUE_STRONG_THRESHOLD = 0.5


_ENV_BY_PHASE = {
    "late_night": "夜里很安静，屋里只剩台灯的光",
    "early_morning": "清早，天刚亮，外面有点凉",
    "forenoon": "上午光线很亮，人挺清醒",
    "noon": "正午，外面有点热闹",
    "afternoon": "下午，光线斜进来，有点慵懒",
    "evening": "傍晚，天色慢慢暗下来",
    "night": "晚上，屋里安安静静",
}


def _local_now(now: datetime) -> datetime:
    """转换到中国标准时间（UTC+8，无夏令时），让生活时段贴近南宁本地。"""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone(timedelta(hours=8)))


def _time_phase(now: datetime) -> str:
    """由本地小时确定性映射到生活化时段，绝不返回 'unknown'。"""
    h = _local_now(now).hour
    if 5 <= h < 8:
        return "early_morning"
    if 8 <= h < 11:
        return "forenoon"
    if 11 <= h < 13:
        return "noon"
    if 13 <= h < 17:
        return "afternoon"
    if 17 <= h < 19:
        return "evening"
    if 19 <= h < 23:
        return "night"
    return "late_night"
