import asyncio

from app.config import PROACTIVE_CHECK_INTERVAL_SECONDS, PROACTIVE_MODE
from app.services.proactive import state
from app.services.proactive.runner import run_proactive_check_once
from app.utils.logging_utils import log_event, new_trace_id


async def scheduler_loop() -> None:
    while True:
        trace_id = new_trace_id()
        try:
            result = await run_proactive_check_once(trace_id=trace_id)
            log_event(
                "proactive",
                "proactive_check",
                trace_id=trace_id,
                action=result.get("action") or ("skipped" if result.get("skipped") else "checked"),
                success=result.get("success"),
                skipped=result.get("skipped"),
                reason=result.get("reason") or result.get("error"),
                candidate_id=result.get("candidate_id"),
                target_label=result.get("target_label"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(
                "proactive",
                "proactive_auto_failed",
                trace_id=trace_id,
                action="scheduler_check",
                success=False,
                reason=type(exc).__name__,
            )
        await asyncio.sleep(PROACTIVE_CHECK_INTERVAL_SECONDS)


def start_proactive_scheduler() -> asyncio.Task | None:
    if PROACTIVE_MODE == "off":
        log_event(
            "proactive",
            "proactive_rule_skipped",
            action="scheduler_start",
            success=True,
            skipped=True,
            reason="proactive mode off",
            proactive_mode=PROACTIVE_MODE,
        )
        return None
    if state.scheduler_task is not None and not state.scheduler_task.done():
        return state.scheduler_task
    state.scheduler_task = asyncio.create_task(scheduler_loop())
    log_event(
        "proactive",
        "proactive_check",
        action="scheduler_started",
        success=True,
        auto_send=PROACTIVE_MODE == "auto",
        dry_run=PROACTIVE_MODE == "dry_run",
        proactive_mode=PROACTIVE_MODE,
    )
    return state.scheduler_task


async def stop_proactive_scheduler() -> None:
    if state.scheduler_task is None or state.scheduler_task.done():
        state.scheduler_task = None
        return
    state.scheduler_task.cancel()
    try:
        await state.scheduler_task
    except asyncio.CancelledError:
        pass
    state.scheduler_task = None
