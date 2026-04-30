from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.utils.logging_utils import log_event, new_trace_id


BurstHandler = Callable[[str, str], object]


class BurstMergeFuture:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._result: object | None = None
        self._exception: BaseException | None = None

    def set_result(self, result: object) -> None:
        self._result = result
        self._event.set()

    def set_exception(self, exc: BaseException) -> None:
        self._exception = exc
        self._event.set()

    def wait(self) -> object:
        self._event.wait()
        if self._exception is not None:
            raise self._exception
        return self._result


@dataclass
class BurstSubmitResult:
    accepted: bool
    future: BurstMergeFuture | None = None
    buffered_count: int = 0
    is_new_buffer: bool = False
    flush_requested: bool = False


@dataclass
class _BurstBuffer:
    session_id: str
    handler: BurstHandler
    future: BurstMergeFuture
    messages: list[str] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    timer: threading.Timer | None = None


class BurstMergeService:
    def __init__(self, *, window_seconds: float, max_messages: int) -> None:
        self.window_seconds = max(0.1, float(window_seconds))
        self.max_messages = max(1, int(max_messages))
        self._buffers: dict[str, _BurstBuffer] = {}
        self._lock = threading.RLock()

    def submit_burst_message(
        self,
        *,
        session_id: str,
        message: str,
        trace_id: str | None,
        handler: BurstHandler,
    ) -> BurstSubmitResult:
        text = message.strip() if isinstance(message, str) else ""
        if not text:
            return BurstSubmitResult(accepted=False)

        flush_requested = False
        with self._lock:
            buffer = self._buffers.get(session_id)
            if buffer is None:
                future = BurstMergeFuture()
                buffer = _BurstBuffer(
                    session_id=session_id,
                    handler=handler,
                    future=future,
                    messages=[text],
                    trace_ids=[trace_id or new_trace_id()],
                )
                timer = threading.Timer(
                    self.window_seconds,
                    self.flush_session,
                    kwargs={"session_id": session_id, "reason": "window_elapsed"},
                )
                timer.daemon = True
                buffer.timer = timer
                self._buffers[session_id] = buffer
                timer.start()
                log_event(
                    "platform",
                    "burst_buffer_started",
                    trace_id=trace_id,
                    session_id=session_id,
                    message_len=len(text),
                    burst_window_seconds=self.window_seconds,
                    burst_max_count=self.max_messages,
                )
                if self.max_messages <= 1:
                    self._start_flush_thread(session_id=session_id, reason="max_messages")
                return BurstSubmitResult(
                    accepted=True,
                    future=future,
                    buffered_count=1,
                    is_new_buffer=True,
                    flush_requested=self.max_messages <= 1,
                )

            buffer.messages.append(text)
            buffer.trace_ids.append(trace_id or new_trace_id())
            buffered_count = len(buffer.messages)
            log_event(
                "platform",
                "burst_message_appended",
                trace_id=trace_id,
                session_id=session_id,
                message_len=len(text),
                burst_buffered_count=buffered_count,
            )
            if buffered_count >= self.max_messages:
                flush_requested = True

        if flush_requested:
            self._start_flush_thread(session_id=session_id, reason="max_messages")

        return BurstSubmitResult(
            accepted=True,
            future=buffer.future,
            buffered_count=buffered_count,
            flush_requested=flush_requested,
        )

    def _start_flush_thread(self, *, session_id: str, reason: str) -> None:
        thread = threading.Thread(
            target=self.flush_session,
            kwargs={"session_id": session_id, "reason": reason},
            daemon=True,
        )
        thread.start()

    def flush_session(self, *, session_id: str, reason: str) -> None:
        with self._lock:
            buffer = self._buffers.pop(session_id, None)
            if buffer is None:
                return
            if buffer.timer is not None:
                buffer.timer.cancel()

        merged_message = "\n".join(buffer.messages)
        trace_id = buffer.trace_ids[0] if buffer.trace_ids else None
        merged_count = len(buffer.messages)
        elapsed_ms = int((time.monotonic() - buffer.started_at) * 1000)
        log_event(
            "platform",
            "burst_flushed",
            trace_id=trace_id,
            session_id=session_id,
            reason=reason,
            burst_merged_count=merged_count,
            merged_message_len=len(merged_message),
            elapsed_ms=elapsed_ms,
        )
        log_event(
            "platform",
            "burst_merged_count",
            trace_id=trace_id,
            session_id=session_id,
            burst_merged_count=merged_count,
        )

        try:
            result = buffer.handler(session_id, merged_message)
        except BaseException as exc:
            buffer.future.set_exception(exc)
            return
        buffer.future.set_result(result)
