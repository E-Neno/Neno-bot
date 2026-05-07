import pytest

from app.services.session_submit_controller import SessionSubmitController


def test_session_submit_controller_keeps_order_when_later_item_is_ready_first():
    controller = SessionSubmitController()
    ticket_1 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-1")
    ticket_2 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-2")

    future_2 = controller.submit_ready(
        ticket=ticket_2,
        handler=lambda: "second",
    )
    future_1 = controller.submit_ready(
        ticket=ticket_1,
        handler=lambda: "first",
    )

    assert future_1.wait() == "first"
    assert future_2.wait() == "second"


def test_session_submit_controller_releases_later_item_after_prior_failure():
    controller = SessionSubmitController()
    ticket_1 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-1")
    ticket_2 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-2")

    def raise_boom() -> None:
        raise RuntimeError("boom")

    future_2 = controller.submit_ready(
        ticket=ticket_2,
        handler=lambda: "second",
    )
    future_1 = controller.submit_ready(
        ticket=ticket_1,
        handler=raise_boom,
    )

    with pytest.raises(RuntimeError, match="boom"):
        future_1.wait()
    assert future_2.wait() == "second"
