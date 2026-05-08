from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.utils.logging_utils import log_event


SubmitHandler = Callable[[], object]
TERMINAL_SUBMIT_STATES = {"completed", "failed", "fallback_completed"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


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
    received_at: str = field(default_factory=_now_iso)


@dataclass
class _ReadySubmit:
    ticket: SubmitTicket
    handler: SubmitHandler
    future: SessionSubmitFuture
    completion_state: str = "completed"
    ready_at: float = field(default_factory=time.monotonic)


@dataclass
class _SessionSubmitState:
    next_arrival_seq: int = 1
    next_submit_seq: int = 1
    ready_items: dict[int, _ReadySubmit] = field(default_factory=dict)
    tracked_items: dict[int, dict[str, object | None]] = field(default_factory=dict)
    worker_running: bool = False


class SessionSubmitController:
    def __init__(self, *, recent_limit: int = 200) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionSubmitState] = {}
        self._recent_limit = max(20, recent_limit)
        self._recent_items: list[dict[str, object | None]] = []

    def _session_state(self, session_id: str) -> _SessionSubmitState:
        return self._sessions.setdefault(session_id, _SessionSubmitState())

    def _base_snapshot(self, ticket: SubmitTicket) -> dict[str, object | None]:
        return {
            "session_id": ticket.session_id,
            "arrival_seq": ticket.arrival_seq,
            "trace_id": ticket.trace_id,
            "submit_state": "received",
            "phase": "ingress",
            "controller_mode": "session_serial_submit",
            "message_type": None,
            "received_at": ticket.received_at,
            "preprocessing_started_at": None,
            "ready_at": None,
            "waiting_started_at": None,
            "submit_started_at": None,
            "completed_at": None,
            "failed_at": None,
            "failed_phase": None,
            "fallback_completed_at": None,
            "blocked_by_seq": None,
            "submit_seq": None,
            "queue_wait_ms": None,
            "submit_latency_ms": None,
            "error_type": None,
            "error_message": None,
            "updated_at": ticket.received_at,
        }

    def _copy_snapshot(self, snapshot: dict[str, object | None]) -> dict[str, object | None]:
        return dict(snapshot)

    def _append_recent_snapshot(self, snapshot: dict[str, object | None]) -> None:
        self._recent_items.append(self._copy_snapshot(snapshot))
        if len(self._recent_items) > self._recent_limit:
            self._recent_items = self._recent_items[-self._recent_limit :]

    def _update_snapshot(
        self,
        snapshot: dict[str, object | None],
        *,
        submit_state: str | None = None,
        phase: str | None = None,
        message_type: str | None = None,
        blocked_by_seq: int | None | object = None,
        error_type: str | None = None,
        error_message: str | None = None,
        failed_phase: str | None = None,
        submit_seq: int | None = None,
        queue_wait_ms: int | None = None,
        submit_latency_ms: int | None = None,
        timestamp_field: str | None = None,
    ) -> dict[str, object | None]:
        now = _now_iso()
        if submit_state is not None:
            snapshot["submit_state"] = submit_state
        if phase is not None:
            snapshot["phase"] = phase
        if message_type is not None:
            snapshot["message_type"] = message_type
        if blocked_by_seq is not None:
            snapshot["blocked_by_seq"] = blocked_by_seq
        if error_type is not None:
            snapshot["error_type"] = error_type
        if error_message is not None:
            snapshot["error_message"] = error_message
        if failed_phase is not None:
            snapshot["failed_phase"] = failed_phase
        if submit_seq is not None:
            snapshot["submit_seq"] = submit_seq
        if queue_wait_ms is not None:
            snapshot["queue_wait_ms"] = queue_wait_ms
        if submit_latency_ms is not None:
            snapshot["submit_latency_ms"] = submit_latency_ms
        if timestamp_field:
            snapshot[timestamp_field] = now
        snapshot["updated_at"] = now
        return snapshot

    def mark_state(
        self,
        *,
        ticket: SubmitTicket,
        submit_state: str,
        phase: str,
        message_type: str | None = None,
        blocked_by_seq: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        failed_phase: str | None = None,
    ) -> dict[str, object | None]:
        with self._lock:
            state = self._session_state(ticket.session_id)
            snapshot = state.tracked_items.setdefault(ticket.arrival_seq, self._base_snapshot(ticket))
            timestamp_field = None
            if submit_state == "preprocessing":
                timestamp_field = "preprocessing_started_at"
            elif submit_state == "ready":
                timestamp_field = "ready_at"
            elif submit_state == "waiting_for_turn":
                timestamp_field = "waiting_started_at"
            elif submit_state == "fallback_completed":
                timestamp_field = "fallback_completed_at"
            elif submit_state == "failed":
                timestamp_field = "failed_at"
            self._update_snapshot(
                snapshot,
                submit_state=submit_state,
                phase=phase,
                message_type=message_type,
                blocked_by_seq=blocked_by_seq,
                error_type=error_type,
                error_message=error_message,
                failed_phase=failed_phase,
                timestamp_field=timestamp_field,
            )
            copied = self._copy_snapshot(snapshot)
            if submit_state in TERMINAL_SUBMIT_STATES:
                self._append_recent_snapshot(copied)

        log_event(
            "platform",
            "session_submit_state_changed",
            trace_id=ticket.trace_id,
            session_id=ticket.session_id,
            arrival_seq=ticket.arrival_seq,
            submit_state=submit_state,
            phase=phase,
            message_type=message_type,
            blocked_by_seq=blocked_by_seq,
            failed_phase=failed_phase,
            error_type=error_type,
            error_message=error_message,
        )
        return copied

    def get_ticket_snapshot(self, *, ticket: SubmitTicket) -> dict[str, object | None] | None:
        with self._lock:
            state = self._sessions.get(ticket.session_id)
            if state is not None:
                snapshot = state.tracked_items.get(ticket.arrival_seq)
                if snapshot is not None:
                    return self._copy_snapshot(snapshot)
            for snapshot in reversed(self._recent_items):
                if snapshot.get("session_id") == ticket.session_id and snapshot.get("arrival_seq") == ticket.arrival_seq:
                    return self._copy_snapshot(snapshot)
        return None

    def get_session_snapshot(self, *, session_id: str) -> dict[str, object]:
        with self._lock:
            state = self._sessions.get(session_id)
            active_items = []
            if state is not None:
                active_items = [
                    self._copy_snapshot(state.tracked_items[arrival_seq])
                    for arrival_seq in sorted(state.tracked_items)
                ]
            recent_items = [
                self._copy_snapshot(item)
                for item in self._recent_items
                if item.get("session_id") == session_id
            ]

        active_keys = {
            (item.get("session_id"), item.get("arrival_seq"))
            for item in active_items
        }
        deduped_recent = [
            item
            for item in recent_items
            if (item.get("session_id"), item.get("arrival_seq")) not in active_keys
        ]
        return {
            "session_id": session_id,
            "active": active_items,
            "recent": deduped_recent,
        }

    def allocate_ticket(self, *, session_id: str, trace_id: str | None = None) -> SubmitTicket:
        ticket: SubmitTicket
        with self._lock:
            state = self._session_state(session_id)
            arrival_seq = state.next_arrival_seq
            state.next_arrival_seq += 1
            ticket = SubmitTicket(
                session_id=session_id,
                arrival_seq=arrival_seq,
                trace_id=trace_id,
            )
            state.tracked_items[arrival_seq] = self._base_snapshot(ticket)

        log_event(
            "platform",
            "session_submit_ingress_allocated",
            trace_id=trace_id,
            session_id=session_id,
            arrival_seq=arrival_seq,
            submit_state="received",
            phase="ingress",
        )
        return ticket

    def submit_ready(
        self,
        *,
        ticket: SubmitTicket,
        handler: SubmitHandler,
        completion_state: str = "completed",
    ) -> SessionSubmitFuture:
        future = SessionSubmitFuture()
        start_worker = False
        waiting_for_seq = None

        with self._lock:
            state = self._session_state(ticket.session_id)
            state.ready_items[ticket.arrival_seq] = _ReadySubmit(
                ticket=ticket,
                handler=handler,
                future=future,
                completion_state=completion_state,
            )
            waiting_for_seq = state.next_submit_seq
            tracked = state.tracked_items.setdefault(ticket.arrival_seq, self._base_snapshot(ticket))
            next_state = "ready" if ticket.arrival_seq == state.next_submit_seq else "waiting_for_turn"
            timestamp_field = "ready_at" if next_state == "ready" else "waiting_started_at"
            self._update_snapshot(
                tracked,
                submit_state=next_state,
                phase="submit_queue",
                blocked_by_seq=None if next_state == "ready" else state.next_submit_seq,
                timestamp_field=timestamp_field,
            )
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
            submit_state="ready" if ticket.arrival_seq == waiting_for_seq else "waiting_for_turn",
            blocked_by_seq=None if ticket.arrival_seq == waiting_for_seq else waiting_for_seq,
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
                        state.tracked_items = {}
                    return

                tracked = state.tracked_items.setdefault(current.ticket.arrival_seq, self._base_snapshot(current.ticket))
                state.next_submit_seq += 1
                self._update_snapshot(
                    tracked,
                    submit_state="submitting",
                    phase="submit",
                    blocked_by_seq=None,
                    submit_seq=submit_seq,
                    timestamp_field="submit_started_at",
                )
                for waiting_seq, waiting_item in state.ready_items.items():
                    waiting_snapshot = state.tracked_items.setdefault(
                        waiting_seq,
                        self._base_snapshot(waiting_item.ticket),
                    )
                    self._update_snapshot(
                        waiting_snapshot,
                        submit_state="waiting_for_turn",
                        phase="submit_queue",
                        blocked_by_seq=current.ticket.arrival_seq,
                    )
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
                submit_state="submitting",
            )

            started = time.monotonic()
            try:
                result = current.handler()
            except BaseException as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                current.future.set_exception(exc)
                with self._lock:
                    state = self._sessions.get(session_id)
                    tracked = None if state is None else state.tracked_items.get(current.ticket.arrival_seq)
                    failed_phase = str((tracked or {}).get("failed_phase") or "submit")
                    if tracked is not None:
                        self._update_snapshot(
                            tracked,
                            submit_state="failed",
                            phase=failed_phase,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            failed_phase=failed_phase,
                            submit_seq=submit_seq,
                            queue_wait_ms=wait_ms,
                            submit_latency_ms=latency_ms,
                            timestamp_field="failed_at",
                        )
                        self._append_recent_snapshot(tracked)
                log_event(
                    "platform",
                    "session_submit_failed",
                    trace_id=current.ticket.trace_id,
                    session_id=session_id,
                    arrival_seq=current.ticket.arrival_seq,
                    submit_seq=submit_seq,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    failed_phase=(tracked or {}).get("failed_phase") if tracked is not None else "submit",
                    latency_ms=latency_ms,
                    submit_state="failed",
                )
            else:
                latency_ms = int((time.monotonic() - started) * 1000)
                current.future.set_result(result)
                terminal_field = "fallback_completed_at" if current.completion_state == "fallback_completed" else "completed_at"
                with self._lock:
                    state = self._sessions.get(session_id)
                    tracked = None if state is None else state.tracked_items.get(current.ticket.arrival_seq)
                    if tracked is not None:
                        self._update_snapshot(
                            tracked,
                            submit_state=current.completion_state,
                            phase="submit" if current.completion_state == "completed" else "preprocess",
                            submit_seq=submit_seq,
                            queue_wait_ms=wait_ms,
                            submit_latency_ms=latency_ms,
                            timestamp_field=terminal_field,
                        )
                        self._append_recent_snapshot(tracked)
                log_event(
                    "platform",
                    "session_submit_finished",
                    trace_id=current.ticket.trace_id,
                    session_id=session_id,
                    arrival_seq=current.ticket.arrival_seq,
                    submit_seq=submit_seq,
                    latency_ms=latency_ms,
                    submit_state=current.completion_state,
                )
