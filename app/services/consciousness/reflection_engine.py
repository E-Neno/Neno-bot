from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from app.storage import db as db_storage

from .config import ConsciousnessConfig
from .experience_recorder import ExperienceRecorder
from .memory_recall import MemoryRecall
from .models import LifeResidue, StateMutation
from .state_store import StateStore


async def _llm_reflect(*, experiences: list[dict[str, Any]], state: Any, config: ConsciousnessConfig) -> dict[str, Any]:
    raise RuntimeError("reflection model calls are disabled unless explicitly enabled and mocked")


class ReflectionEngine:
    def __init__(
        self,
        state_store: StateStore,
        recorder: ExperienceRecorder,
        recall: MemoryRecall,
        config: ConsciousnessConfig,
    ) -> None:
        self._state_store = state_store
        self._recorder = recorder
        self._recall = recall
        self._config = config

    async def dry_run(self, trace_id: str | None = None) -> dict[str, Any]:
        state = await self._state_store.read()
        experiences = _today_experiences(await self._recorder.list_recent(limit=200))
        if not experiences:
            return {
                "success": True,
                "enabled": self._config.reflection_enabled,
                "action": "no_experiences",
                "trace_id": trace_id,
                "input_summary": "",
                "output": None,
            }

        output = await self._build_output(experiences, state)
        return {
            "success": True,
            "enabled": self._config.reflection_enabled,
            "action": "would_reflect",
            "trace_id": trace_id,
            "input_summary": _input_summary(experiences),
            "output": output,
        }

    async def run_once(self, trace_id: str | None = None) -> dict[str, Any]:
        if not self._config.reflection_enabled:
            return {
                "success": True,
                "enabled": False,
                "action": "disabled",
            }

        state = await self._state_store.read()
        experiences = _today_experiences(await self._recorder.list_recent(limit=200))
        input_summary = _input_summary(experiences)

        if not experiences:
            run_id = await asyncio.to_thread(
                _insert_reflection_run,
                trace_id or "",
                "skipped",
                "",
                None,
                None,
                None,
            )
            return {
                "success": True,
                "enabled": True,
                "action": "no_experiences",
                "run_id": run_id,
            }

        output = await self._build_output(experiences, state)
        run_id = await asyncio.to_thread(
            _insert_reflection_run,
            trace_id or "",
            "completed",
            input_summary,
            output,
            None,
            None,
        )

        for memory in output.get("memories", [])[:2]:
            await self._recall.add_memory(
                content=memory.get("content", ""),
                tags=memory.get("tags", ["life"]),
                subject=memory.get("subject") or None,
                salience=float(memory.get("salience", 0.5)),
            )

        feedback = output.get("state_feedback", {})
        life_residue_data = feedback.get("life_residue") or {}
        await self._state_store.submit_mutation(
            StateMutation(
                trace_id=trace_id or "",
                reason="reflection feedback",
                mood_valence_delta=float(feedback.get("mood_valence_delta", 0.0)),
                desire_pulse=float(feedback.get("desire_pulse", 0.0)),
                life_residue=LifeResidue.model_validate(life_residue_data),
            )
        )

        return {
            "success": True,
            "enabled": True,
            "action": "reflected",
            "run_id": run_id,
            "output": output,
        }

    async def _build_output(self, experiences: list[dict[str, Any]], state: Any) -> dict[str, Any]:
        if self._config.reflection_model_enabled:
            return await _llm_reflect(experiences=experiences, state=state, config=self._config)
        return _deterministic_output(experiences)


def _deterministic_output(experiences: list[dict[str, Any]]) -> dict[str, Any]:
    recent = experiences[:3]
    summary = " / ".join(exp.get("content", "") for exp in recent if exp.get("content"))
    high_salience = [exp for exp in experiences if float(exp.get("salience") or 0.0) >= 0.7]
    memories = [
        {
            "content": exp.get("content", ""),
            "tags": ["life", exp.get("source", "experience"), exp.get("kind", "reflection")],
            "subject": "",
            "salience": min(1.0, max(0.0, float(exp.get("salience") or 0.5))),
        }
        for exp in high_salience[:2]
        if exp.get("content")
    ]
    residue_source = high_salience[0] if high_salience else recent[0]
    residue_topic = residue_source.get("content", "") if residue_source else ""
    residue_intensity = min(1.0, max(0.0, float(residue_source.get("salience") or 0.3))) if residue_source else 0.0
    return {
        "summary": summary,
        "memories": memories,
        "state_feedback": {
            "mood_valence_delta": 0.02 if experiences else 0.0,
            "desire_pulse": 0.0,
            "life_residue": {
                "topic": residue_topic,
                "mood": "reflective",
                "intensity": residue_intensity,
            },
        },
    }


def _today_experiences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    result: list[dict[str, Any]] = []
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
        if parsed.astimezone(timezone.utc).date() == today:
            result.append(row)
    return result


def _input_summary(experiences: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- [{exp.get('source')}/{exp.get('kind')}] {exp.get('content', '')}"
        for exp in experiences[:20]
    )


def _insert_reflection_run(
    trace_id: str,
    status: str,
    input_summary: str,
    output: dict[str, Any] | None,
    model_name: str | None,
    error: str | None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    completed_at = now if status in {"completed", "skipped"} else None
    with db_storage.get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO dream_reflection_runs (
                trace_id,
                status,
                input_summary,
                output_json,
                model_name,
                error,
                created_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                status,
                input_summary,
                json.dumps(output, ensure_ascii=False) if output is not None else None,
                model_name,
                error,
                now,
                completed_at,
            ),
        )
        return int(cursor.lastrowid)
