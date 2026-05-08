import time

from app.services.session_aggregation_controller import SessionAggregationController


def test_session_aggregation_controller_batches_messages_within_window():
    controller = SessionAggregationController(window_seconds=0.03)
    ticket_1 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-1")
    ticket_2 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-2")
    handled = []

    future_1 = controller.mark_ready(
        ticket=ticket_1,
        message="第一句",
        input_record={"message_type": "text", "source": "platform:wx"},
        handler=lambda batch: handled.append(
            [item.ticket.arrival_seq for item in batch.source_messages]
        ) or "ok",
    )
    future_2 = controller.mark_ready(
        ticket=ticket_2,
        message="第二句",
        input_record={"message_type": "text", "source": "platform:wx"},
        handler=lambda batch: "ok",
    )

    assert future_1.wait() == "ok"
    assert future_2.wait() == "ok"
    assert handled == [[1, 2]]


def test_session_aggregation_controller_splits_messages_after_window():
    controller = SessionAggregationController(window_seconds=0.02)
    handled = []

    ticket_1 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-1")
    future_1 = controller.mark_ready(
        ticket=ticket_1,
        message="第一句",
        input_record={"message_type": "text", "source": "platform:wx"},
        handler=lambda batch: handled.append(batch.batch_id) or "first",
    )
    assert future_1.wait() == "first"

    time.sleep(0.04)

    ticket_2 = controller.allocate_ticket(session_id="wx:private:test-user", trace_id="trace-2")
    future_2 = controller.mark_ready(
        ticket=ticket_2,
        message="第二句",
        input_record={"message_type": "text", "source": "platform:wx"},
        handler=lambda batch: handled.append(batch.batch_id) or "second",
    )
    assert future_2.wait() == "second"
    assert handled[0] != handled[1]
