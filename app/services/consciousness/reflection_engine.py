from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.storage import db as db_storage

from .config import ConsciousnessConfig
from .experience_recorder import ExperienceRecorder
from .memory_recall import MemoryRecall
from .models import LifeResidue, StateMutation
from .self_facts import (
    guard_self_fact, learn_fact_content, learn_fact_tag,
    self_fact_content, self_fact_tag,
)
from .state_store import StateStore

if TYPE_CHECKING:
    from .activity_episode_store import ActivityEpisodeStore

_log = logging.getLogger(__name__)
_TZ_8 = timezone(timedelta(hours=8))


async def _llm_reflect(
    *, experiences: list[dict[str, Any]], state: Any, config: ConsciousnessConfig
) -> dict[str, Any]:
    raise RuntimeError(
        "reflection model calls are disabled unless explicitly enabled and mocked"
    )


class ReflectionEngine:
    def __init__(
        self,
        state_store: StateStore,
        recorder: ExperienceRecorder,
        recall: MemoryRecall,
        config: ConsciousnessConfig,
        episode_store: "ActivityEpisodeStore | None" = None,  # C1.5
    ) -> None:
        self._state_store = state_store
        self._recorder = recorder
        self._recall = recall
        self._config = config
        self._episode_store = episode_store  # C1.5

    # ── C1.5: today's episode timeline (no internal datetime.now) ─────────
    async def _fetch_today_episodes(self, target_day: date) -> list[dict[str, Any]]:
        """Fetch episodes for *target_day* (UTC+8 calendar day).

        The caller is responsible for computing target_day exactly once so that
        experiences and episodes always use the same boundary.  This method must
        never call datetime.now() internally.
        """
        if self._episode_store is None:
            return []
        try:
            return await self._episode_store.list_for_day(target_day, "+08:00")
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "episode_store.list_for_day failed, degrading to experience-only: %s", exc
            )
            return []

    async def dry_run(
        self,
        trace_id: str | None = None,
        _target_day: date | None = None,  # injection point for tests
    ) -> dict[str, Any]:
        # Gap 1: compute target_day once; both inputs must use this same value.
        target_day = _target_day if _target_day is not None else datetime.now(_TZ_8).date()

        state = await self._state_store.read()
        experiences = _today_experiences(await self._recorder.list_recent(limit=200), target_day)
        episodes = await self._fetch_today_episodes(target_day)

        if not experiences and not episodes:
            return {
                "success": True,
                "enabled": self._config.reflection_enabled,
                "action": "no_experiences",
                "trace_id": trace_id,
                "input_summary": "",
                "output": None,
            }

        output = await self._build_output(experiences, state, episodes=episodes)
        return {
            "success": True,
            "enabled": self._config.reflection_enabled,
            "action": "would_reflect",
            "trace_id": trace_id,
            "input_summary": _input_summary(experiences, episodes=episodes),
            "output": output,
        }

    async def run_once(
        self,
        trace_id: str | None = None,
        _target_day: date | None = None,  # injection point for tests
    ) -> dict[str, Any]:
        if not self._config.reflection_enabled:
            return {
                "success": True,
                "enabled": False,
                "action": "disabled",
            }

        # Gap 1: compute target_day ONCE here; pass to every helper that needs it.
        target_day = _target_day if _target_day is not None else datetime.now(_TZ_8).date()

        state = await self._state_store.read()
        experiences = _today_experiences(await self._recorder.list_recent(limit=200), target_day)
        episodes = await self._fetch_today_episodes(target_day)
        input_summary = _input_summary(experiences, episodes=episodes)

        if not experiences and not episodes:
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

        output = await self._build_output(experiences, state, episodes=episodes)
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

        # 自我库（刀①阶段3）：反复经历结晶成 subject="neno" 归纳偏好。
        # 放在普通记忆落库之后，写库/去重/强化/防身份膨胀守门都在这一步。
        await self._crystallize_self_facts(output.get("self_fact_candidates", []))
        # 学习（刀①收尾）：当天 learning 经历结晶成 subject="neno" 直接事实。
        await self._crystallize_learn_facts(output.get("learn_fact_candidates", []))

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

    async def _build_output(
        self,
        experiences: list[dict[str, Any]],
        state: Any,
        episodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self._config.reflection_model_enabled:
            return await _llm_reflect(
                experiences=experiences, state=state, config=self._config
            )
        return _deterministic_output(experiences, episodes=episodes or [], state=state)

    async def _crystallize_self_facts(
        self, candidates: list[dict[str, Any]]
    ) -> None:
        """反复经历 → subject="neno" 归纳偏好。写一次去重、复现强化、防身份膨胀。

        防伪：只接 reflection 看到的落账活动统计，聊天进不来。做过≠身份——
        守门器挡身份/传记词与数字；过不了的候选直接跳过，不留旧值之外的脏数据。
        """
        for cand in candidates or []:
            key = str(cand.get("key", "")).strip()
            if not key:
                continue
            label = str(cand.get("label", "") or key).strip()
            tag = self_fact_tag(key)
            existing_id = await asyncio.to_thread(_find_self_fact_id, tag)
            if existing_id is not None:
                # 复现 → 强化（随时间挣得稳定），不写重复
                await self._recall.update_salience(existing_id, 0.05)
                continue
            content = self_fact_content(label)
            if not guard_self_fact(content):
                _log.warning("self_fact guard rejected crystallization: %r", content)
                continue
            await self._recall.add_memory(
                content=content,
                tags=["self", "neno", "preference", tag],
                subject="neno",
                salience=0.5,
            )

    async def _crystallize_learn_facts(
        self, candidates: list[dict[str, Any]]
    ) -> None:
        """学习落账经历 → subject="neno" 直接事实「你最近在学着上手 X」。

        学习是有持续身份意义的直接事实，单次即可结晶（不必反复）；按主题去重、
        复现强化。守门挡身份/学历词——学某事推不出科班/专业。
        """
        for cand in candidates or []:
            topic = str(cand.get("topic", "")).strip()
            if not topic:
                continue
            tag = learn_fact_tag(topic)
            existing_id = await asyncio.to_thread(_find_self_fact_id, tag)
            if existing_id is not None:
                await self._recall.update_salience(existing_id, 0.05)
                continue
            content = learn_fact_content(topic)
            if not guard_self_fact(content):
                _log.warning("learn_fact guard rejected crystallization: %r", content)
                continue
            await self._recall.add_memory(
                content=content,
                tags=["self", "neno", "learning", tag],
                subject="neno",
                salience=0.55,
            )


# ── Deterministic reflection (C1.5 upgraded) ─────────────────────────────

def _deterministic_output(
    experiences: list[dict[str, Any]],
    episodes: list[dict[str, Any]] | None = None,
    state: Any = None,
) -> dict[str, Any]:
    """Build a deterministic reflection summary.

    With *episodes* (C1.5 mode):
    - Summary: activity count, first/last label, transition count, interrupt count,
      most-frequent place (frequency-ordered, ties by first occurrence), daily_intent.
    - residue.topic priority: high-salience experience (≥0.7) > best life_simulation
      MicroEvent (any salience) > last episode label > first experience.
    - long_term_memory written only for: repeated activity patterns (same key ≥2),
      frequent interrupts (≥2), or persistent residue (intensity ≥0.5).
      Single ordinary episodes NEVER produce LTM entries.

    Without *episodes* (experience-only / legacy mode):
    - All original behaviour preserved verbatim.
    """
    episodes = episodes or []
    recent = experiences[:3]
    high_salience = [e for e in experiences if float(e.get("salience") or 0.0) >= 0.7]
    # 学习直接事实候选：当天 kind="learning" 的落账经历（单次即可结晶，去重在 run_once）
    learn_fact_candidates = [
        {"topic": str(e.get("content", "")).strip()}
        for e in experiences
        if e.get("kind") == "learning" and str(e.get("content", "")).strip()
    ]

    # ── 1. Build summary ──────────────────────────────────────────────────
    summary_parts: list[str] = []

    if episodes:
        count = len(episodes)
        first_ep = episodes[0]   # list_for_day → ASC by started_at
        last_ep  = episodes[-1]

        # Transitions: adjacent episodes with different activity_key
        transitions = sum(
            1 for a, b in zip(episodes, episodes[1:])
            if a.get("activity_key") != b.get("activity_key")
        )

        # Interrupts
        interrupt_count = sum(
            1 for ep in episodes if ep.get("status") == "interrupted"
        )

        # Most-frequent place (ties → first occurrence wins)
        place_seq = [ep.get("place", "") for ep in episodes if ep.get("place")]
        if place_seq:
            place_counts = Counter(place_seq)
            first_seen: dict[str, int] = {}
            for idx, p in enumerate(place_seq):
                first_seen.setdefault(p, idx)
            main_place = min(
                place_counts,
                key=lambda p: (-place_counts[p], first_seen[p]),
            )
        else:
            main_place = ""

        # daily_intent from LifeState if available
        daily_intent = ""
        if state is not None:
            try:
                daily_intent = state.life.daily_intent or ""
            except AttributeError:
                pass

        summary_parts.append(f"今天共有 {count} 段活动")
        summary_parts.append(f"从「{first_ep.get('activity_label', '')}」开始")
        if count > 1:
            summary_parts.append(f"到「{last_ep.get('activity_label', '')}」结束")
        if transitions:
            summary_parts.append(f"经历了 {transitions} 次活动切换")
        if interrupt_count:
            summary_parts.append(f"被打断 {interrupt_count} 次")
        if main_place:
            summary_parts.append(f"主要场所：{main_place}")
        if daily_intent:
            summary_parts.append(f"今日意图：{daily_intent}")

    else:
        # experience-only mode: fall back to content snippet
        exp_snippet = " / ".join(
            e.get("content", "") for e in recent if e.get("content")
        )
        if exp_snippet:
            summary_parts.append(exp_snippet)

    summary = "，".join(summary_parts)

    # ── 2. Residue topic ──────────────────────────────────────────────────
    # Priority:
    #   1. High-salience experience (any source, salience ≥ 0.7)
    #   2. Best life_simulation MicroEvent (highest salience, any value)
    #   3. Last episode label
    #   4. First experience content
    micro_events = [e for e in experiences if e.get("source") == "life_simulation"]
    best_micro: dict[str, Any] | None = (
        max(micro_events, key=lambda e: float(e.get("salience") or 0.0))
        if micro_events
        else None
    )

    residue_topic = ""
    residue_intensity = 0.3

    if high_salience:
        src = high_salience[0]
        residue_topic = src.get("content", "")
        residue_intensity = min(1.0, float(src.get("salience") or 0.3))
    elif best_micro:
        residue_topic = best_micro.get("content", "")
        residue_intensity = min(1.0, float(best_micro.get("salience") or 0.3))
    elif episodes:
        residue_topic = episodes[-1].get("activity_label", "")
        residue_intensity = 0.3
    elif recent:
        src = recent[0]
        residue_topic = src.get("content", "")
        residue_intensity = min(1.0, float(src.get("salience") or 0.3))

    residue_intensity = min(1.0, max(0.0, residue_intensity))

    # ── 3. Long-term memories ─────────────────────────────────────────────
    memories: list[dict[str, Any]] = []
    # 自我库候选（刀①阶段3）：反复活动 → 归纳偏好结晶 subject="neno"。
    # 单列出来不受 memories[:2] 展示截断影响；写库/去重/强化在 run_once。
    self_fact_candidates: list[dict[str, Any]] = []

    if episodes:
        # 3a. Repeated activity patterns (same activity_key ≥ 2 times)
        activity_counts: Counter[str] = Counter(
            ep.get("activity_key", "") for ep in episodes if ep.get("activity_key")
        )
        for key, cnt in activity_counts.most_common():
            if cnt < 2:
                break
            label = next(
                (
                    ep.get("activity_label", key)
                    for ep in episodes
                    if ep.get("activity_key") == key
                ),
                key,
            )
            memories.append({
                "content": f"今天多次回到「{label}」（{cnt} 次），可能是一种习惯模式",
                "tags": ["life", "pattern", "repeated_activity", self_fact_tag(key)],
                "subject": "",
                "salience": 0.7,
            })
            self_fact_candidates.append({"key": key, "label": label, "count": cnt})

        # 3b. Frequent interrupts (≥ 2)
        total_interrupts = sum(
            1 for ep in episodes if ep.get("status") == "interrupted"
        )
        if total_interrupts >= 2:
            memories.append({
                "content": f"今天有 {total_interrupts} 段活动被打断，注意力容易被外部拉走",
                "tags": ["life", "pattern", "frequent_interrupt"],
                "subject": "",
                "salience": 0.65,
            })

        # 3c. Residue persistence (intensity ≥ 0.5)
        if state is not None:
            try:
                residue = state.life.residue
                if residue.intensity >= 0.5 and residue.topic:
                    memories.append({
                        "content": f"生活余波持续影响：{residue.topic}",
                        "tags": ["life", "residue", "persistence"],
                        "subject": "",
                        "salience": float(residue.intensity),
                    })
            except AttributeError:
                pass

        # Episode mode: no fallback to experience-based LTM.
        # Single ordinary episodes intentionally produce zero LTM entries.

    else:
        # Experience-only mode: original behaviour — high-salience → LTM
        memories = [
            {
                "content": exp.get("content", ""),
                "tags": [
                    "life",
                    exp.get("source", "experience"),
                    exp.get("kind", "reflection"),
                ],
                "subject": "",
                "salience": min(1.0, max(0.0, float(exp.get("salience") or 0.5))),
            }
            for exp in high_salience[:2]
            if exp.get("content")
        ]

    return {
        "summary": summary,
        "memories": memories[:2],
        "self_fact_candidates": self_fact_candidates,
        "learn_fact_candidates": learn_fact_candidates,
        "state_feedback": {
            "mood_valence_delta": 0.02 if (experiences or episodes) else 0.0,
            "desire_pulse": 0.0,
            "life_residue": {
                "topic": residue_topic,
                "mood": "reflective",
                "intensity": residue_intensity,
            },
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def _today_experiences(
    rows: list[dict[str, Any]],
    target_day: date,  # Gap 1: must be pre-computed by caller; no datetime.now() here
) -> list[dict[str, Any]]:
    """Filter *rows* to those whose created_at falls on *target_day* (UTC+8).

    The caller (run_once / dry_run) computes target_day once and passes the same
    value to both _today_experiences and _fetch_today_episodes so that experiences
    and episodes always share an identical calendar-day boundary.
    """
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
        if parsed.astimezone(_TZ_8).date() == target_day:
            result.append(row)
    return result


def _input_summary(
    experiences: list[dict[str, Any]],
    episodes: list[dict[str, Any]] | None = None,
) -> str:
    """Build the audit input string stored in dream_reflection_runs.

    C1.5: prepend episode timeline including metadata.daily_intent so operators
    can audit which intent drove each episode.  Missing or malformed metadata
    is handled safely (defaults to empty string, no crash).
    """
    parts: list[str] = []
    if episodes:
        parts.append(f"[episodes: {len(episodes)}]")
        for ep in episodes:
            # Gap 2: safely extract daily_intent from decoded metadata dict
            meta = ep.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
            daily_intent = meta.get("daily_intent", "")
            parts.append(
                f"  [{ep.get('time_phase', '')}@{ep.get('place', '')}]"
                f" {ep.get('activity_label', '')}"
                f" ({ep.get('status', '')})"
                f" reason={ep.get('reason', '')!r}"
                f" daily_intent={daily_intent!r}"
            )
    parts.extend(
        f"- [{exp.get('source')}/{exp.get('kind')}] {exp.get('content', '')}"
        for exp in experiences[:20]
    )
    return "\n".join(parts)


def _find_self_fact_id(tag: str) -> int | None:
    """查 subject="neno" 且带指定 activity 标签的已有自我事实 id（去重定位）。

    匹配带引号的 JSON 标签形式 `"activity:key"`，避免 activity:read 误命中 activity:reading。
    """
    rows = db_storage.fetch_all(
        "SELECT id FROM long_term_memory WHERE subject = 'neno' AND tags LIKE ? LIMIT 1",
        (f'%"{tag}"%',),
    )
    return int(rows[0]["id"]) if rows else None


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
