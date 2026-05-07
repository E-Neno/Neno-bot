from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.utils.logging_utils import log_event


SubmitHandler = Callable[[], object]


class SessionSubmitFuture:
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


@dataclass(frozen=True)
class SubmitTicket:
    session_id: str
    arrival_seq: int
    trace_id: str | None = None
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class _ReadySubmit:
    ticket: SubmitTicket
    handler: SubmitHandler
    future: SessionSubmitFuture
    ready_at: float = field(default_factory=time.monotonic)


@dataclass
class _SessionSubmitState:
    next_arrival_seq: int = 1
    next_submit_seq: int = 1
    ready_items: dict[int, _ReadySubmit] = field(default_factory=dict)
    worker_running: bool = False


class SessionSubmitController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionSubmitState] = {}

    def allocate_ticket(self, *, session_id: str, trace_id: str | None = None) -> SubmitTicket:
        with self._lock:
            state = self._sessions.setdefault(session_id, _SessionSubmitState())
            arrival_seq = state.next_arrival_seq
            state.next_arrival_seq += 1

        log_event(
            "platform",
            "session_submit_ingress_allocated",
            trace_id=trace_id,
            session_id=session_id,
            arrival_seq=arrival_seq,
        )
        return SubmitTicket(
            session_id=session_id,
            arrival_seq=arrival_seq,
            trace_id=trace_id,
        )

    def submit_ready(
        self,
        *,
        ticket: SubmitTicket,
        handler: SubmitHandler,
    ) -> SessionSubmitFuture:
        future = SessionSubmitFuture()
        start_worker = False
        waiting_for_seq = None

        with self._lock:
            state = self._sessions.setdefault(ticket.session_id, _SessionSubmitState())
            state.ready_items[ticket.arrival_seq] = _ReadySubmit(
                ticket=ticket,
                handler=handler,
                future=future,
            )
            waiting_for_seq = state.next_submit_seq
            if not state.worker_running and ticket.arrival_seq == state.next_submit_seq:
                state.worker_running = True
                start_worker = True

        log_event(
            "platform",
            "session_submit_ready",
            trace_id=ticket.trace_id,
            session_id=ticket.session_id,
            arrival_seq=ticket.arrival_seq,
            waiting_for_seq=waiting_for_seq,
            queued_before_submit=max(0, ticket.arrival_seq - (waiting_for_seq or ticket.arrival_seq)),
        )

        if start_worker:
            thread = threading.Thread(
                target=self._run_session_worker,
                kwargs={"session_id": ticket.session_id},
                daemon=True,
            )
            thread.start()

        return future

    def _run_session_worker(self, *, session_id: str) -> None:
        while True:
            current: _ReadySubmit | None = None
            submit_seq = 0
            queued_remaining = 0

            with self._lock:
                state = self._sessions.get(session_id)
                if state is None:
                    return

                submit_seq = state.next_submit_seq
                current = state.ready_items.pop(submit_seq, None)
                if current is None:
                    state.worker_running = False
                    if not state.ready_items and state.next_submit_seq >= state.next_arrival_seq:
                        self._sessions.pop(session_id, None)
                    return

                state.next_submit_seq += 1
                queued_remaining = len(state.ready_items)

            wait_ms = int((time.monotonic() - current.ticket.created_at) * 1000)
            log_event(
                "platform",
                "session_submit_start",
                trace_id=current.ticket.trace_id,
                session_id=session_id,
                arrival_seq=current.ticket.arrival_seq,
                submit_seq=submit_seq,
                queue_wait_ms=wait_ms,
                queued_remaining=queued_remaining,
            )

            started = time.monotonic()
            try:
                result = current.handler()
            except BaseException as exc:
                current.future.set_exception(exc)
                log_event(
                    "platform",
                    "session_submit_failed",
                    trace_id=current.ticket.trace_id,
                    session_id=session_id,
                    arrival_seq=current.ticket.arrival_seq,
                    submit_seq=submit_seq,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            else:
                current.future.set_result(result)
                log_event(
                    "platform",
                    "session_submit_finished",
                    trace_id=current.ticket.trace_id,
                    session_id=session_id,
                    arrival_seq=current.ticket.arrival_seq,
                    submit_seq=submit_seq,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
