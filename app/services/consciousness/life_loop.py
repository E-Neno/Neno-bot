from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.storage.db import add_debug_event

from .config import ConsciousnessConfig
from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .models import LifeEnvironment, LifeState, StateMutation
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
            "content": f"Neno 正在{life.activity_label}",
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
        # 跳过 life_loop 自己写入的 state_shift 记录，避免它把后续每一轮都永久推进成 absorbed。
        # 只有真正的"没说出口的想法"（如 brain_judge）才应触发 absorbed。
        if row.get("source") == "life_loop":
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
