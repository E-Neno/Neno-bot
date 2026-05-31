import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.storage.db import add_debug_event, fetch_one, get_conn

from .config import ConsciousnessConfig
from .desire import DesireModel
from .models import NenoState, StateMutation
from .mood import MoodModel

logger = logging.getLogger(__name__)

MAX_RETRY = 3


class StateStore:
    """
    AgentState 单写者。所有状态变更必须经此类，不允许外部直接写 agent_state 表。

    并发模型：
    - 读：任意协程可直接调用 read()，无锁（SQLite WAL 保证一致读）
    - 写：外部调用 submit_mutation()，入 asyncio.Queue；
           单一 _writer_loop 协程串行消费，乐观锁 revision 校验后落库
    """

    def __init__(self, db, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config
        self._desire = DesireModel(config)
        self._mood = MoodModel(config)
        self._queue: asyncio.Queue[StateMutation] = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task[None]] = None
        self._started = False

    async def start(self) -> None:
        """启动单写者协程"""
        if self._started:
            return
        self._started = True
        await self._ensure_row_exists()
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        """优雅停止：等待队列清空后取消写者协程"""
        self._started = False
        await self._queue.join()
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            self._writer_task = None

    async def read(self) -> NenoState:
        """从 SQLite 读取当前状态，并实时推算 desire/mood 的当前值"""
        row = fetch_one(
            "SELECT revision, state_json, updated_at FROM agent_state WHERE id = 1 LIMIT 1"
        )
        if row is None:
            state = self._default_state()
        else:
            state = NenoState.model_validate_json(row["state_json"])
            state.revision = int(row["revision"])
            state.updated_at = row["updated_at"]

        now = _utcnow()

        # 实时推算 desire
        state.desire.value = self._desire.current_value(state.desire, now)

        # 实时推算 mood（基线回归），然后更新 label
        new_valence, new_arousal = self._mood.regress_to_baseline(state.mood)
        state.mood.valence = new_valence
        state.mood.arousal = new_arousal
        state.mood.label, state.mood.description = self._mood.to_label(new_valence, new_arousal)

        return state

    async def submit_mutation(self, mutation: StateMutation) -> None:
        """提交状态变更请求，异步入队，不阻塞调用方"""
        await self._queue.put(mutation)

    async def _writer_loop(self) -> None:
        """单写者主循环：取 mutation → 读取当前 revision → 应用 → 乐观锁写入"""
        while self._started:
            try:
                mutation = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            trace_id = str(uuid.uuid4())
            success = False
            for attempt in range(1, MAX_RETRY + 1):
                try:
                    row = fetch_one(
                        "SELECT revision, state_json FROM agent_state WHERE id = 1 LIMIT 1"
                    )
                    if row is None:
                        state = self._default_state()
                        current_revision = 0
                    else:
                        state = NenoState.model_validate_json(row["state_json"])
                        current_revision = int(row["revision"])

                    now = _utcnow()
                    new_state = self._apply_mutation(state, mutation, now)
                    new_state.revision = current_revision + 1
                    new_state.updated_at = now.isoformat()
                    new_json = new_state.model_dump_json()

                    with get_conn() as conn:
                        cursor = conn.execute(
                            """
                            UPDATE agent_state
                            SET revision = ?, state_json = ?, updated_at = ?
                            WHERE id = 1 AND revision = ?
                            """,
                            (new_state.revision, new_json, now.isoformat(), current_revision),
                        )
                        if cursor.rowcount > 0:
                            success = True
                            if attempt > 1:
                                logger.info(
                                    "optimistic lock resolved on attempt %d trace_id=%s",
                                    attempt,
                                    trace_id,
                                )
                            break
                        else:
                            logger.warning(
                                "optimistic lock conflict attempt=%d/%d trace_id=%s revision=%d",
                                attempt,
                                MAX_RETRY,
                                trace_id,
                                current_revision,
                            )
                except Exception:
                    logger.exception(
                        "state_store write error attempt=%d/%d trace_id=%s",
                        attempt,
                        MAX_RETRY,
                        trace_id,
                    )

            if not success:
                add_debug_event(
                    trace_id=trace_id,
                    module="state_store",
                    event="write_failed",
                    level="error",
                    success=False,
                    reason=f"optimistic lock exhausted after {MAX_RETRY} retries",
                    metadata_json=json.dumps(
                        {"trace_id": trace_id},
                        ensure_ascii=False,
                    ),
                )
                logger.error(
                    "state_store write failed after %d retries trace_id=%s",
                    MAX_RETRY,
                    trace_id,
                )

            self._queue.task_done()

    def _apply_mutation(
        self, state: NenoState, mutation: StateMutation, now: datetime
    ) -> NenoState:
        """将 StateMutation 应用到 NenoState，返回新状态（纯函数，不写库）"""

        if mutation.energy is not None:
            state.energy = mutation.energy

        if mutation.mood is not None:
            state.mood = mutation.mood
            state.mood.label, state.mood.description = self._mood.to_label(
                state.mood.valence, state.mood.arousal
            )

        if mutation.desire is not None:
            state.desire = mutation.desire

        if mutation.world is not None:
            state.world = mutation.world
            state.world.last_perception_at = now.isoformat()

        if mutation.today_experiences_append is not None:
            state.today_experiences.append(mutation.today_experiences_append)
            if len(state.today_experiences) > self._cfg.today_experiences_max:
                state.today_experiences = state.today_experiences[
                    -self._cfg.today_experiences_max:
                ]

        if mutation.today_experiences_clear:
            state.today_experiences.clear()

        if mutation.mood_valence_delta != 0.0:
            new_valence, new_arousal = self._mood.apply_event(
                state.mood, mutation.mood_valence_delta, 0.0, now
            )
            state.mood.valence = new_valence
            state.mood.arousal = new_arousal
            state.mood.label, state.mood.description = self._mood.to_label(
                new_valence, new_arousal
            )

        if mutation.desire_pulse > 0.0:
            state.desire.value = max(0.0, min(100.0, state.desire.value + mutation.desire_pulse))

        return state

    async def _ensure_row_exists(self) -> None:
        """首次启动时若 agent_state 表为空，插入默认状态行"""
        row = fetch_one("SELECT id FROM agent_state WHERE id = 1 LIMIT 1")
        if row is not None:
            return
        default = self._default_state()
        default_json = default.model_dump_json()
        now = _utcnow()
        with get_conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_state (id, revision, state_json, updated_at)
                VALUES (1, 0, ?, ?)
                """,
                (default_json, now.isoformat()),
            )

    def _default_state(self) -> NenoState:
        """构建默认 NenoState"""
        return NenoState()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
