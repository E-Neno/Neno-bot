"""InterruptController — three-phase state machine for brain interruption."""
import asyncio
import logging
from typing import Literal

logger = logging.getLogger(__name__)

Phase = Literal["idle", "judging", "generating", "sending"]


class InterruptController:
    """
    三态打断规则状态机。
    - idle      → 无事发生
    - judging   → DeepSeek 判断中（P0 到达可无损取消）
    - generating→ Gemini 生成中（P0 到达：发完当前条，不追加）
    - sending   → 碎片发送中（P0 到达：剩余丢弃，"被打断"入事件池）

    全程 asyncio，无 threading 锁，无死锁风险。
    """

    def __init__(self) -> None:
        self._phase: Phase = "idle"
        self._cancel_event = asyncio.Event()
        self._stop_after_current = False

    @property
    def phase(self) -> Phase:
        return self._phase

    def enter(self, phase: Phase) -> None:
        self._phase = phase
        if phase == "judging":
            self._cancel_event.clear()
        if phase == "idle":
            self._stop_after_current = False

    async def on_p0_interrupt(self, pool=None) -> None:
        """P0 用户消息到达时调用"""
        if self._phase == "judging":
            self._cancel_event.set()
            logger.info("interrupt: cancelled judging")
        elif self._phase in ("generating", "sending"):
            self._stop_after_current = True
            logger.info(f"interrupt: stop_after_current set in {self._phase}")
            if self._phase == "sending" and pool is not None:
                from .event_pool import EventIn
                await pool.push(EventIn(
                    topic_hash="system_interrupted",
                    priority=2,
                    content="说话说到一半被用户打断了",
                    tags=["系统", "打断"],
                    mood_impact=-0.05,
                    source="system",
                ))

    @property
    def should_cancel_judging(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def should_stop_after_current(self) -> bool:
        return self._stop_after_current
