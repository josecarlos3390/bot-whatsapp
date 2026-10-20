from __future__ import annotations

from app.agent import Toolbox
from app.models import Cart, Contact, FeedbackRequest, Order
from app.services import feedback


async def _contact(session) -> Contact:
    contact = Contact(wa_id="59170000444", phone_e164="+59170000444")
    session.add(contact)
    await session.commit()
    return contact


async def test_record_feedback_and_summary(session):
    contact = await _contact(session)
    result = await feedback.record_feedback(
        session,
        contact.id,
        type="service",
        rating=5,
        comment="Muy buena atención",
    )
    assert result["ok"] is True
    assert result["needs_attention"] is False

    summary = await feedback.feedback_summary(
        session, contact_id=contact.id
    )
    assert summary["count"] == 1
    assert summary["average_rating"] == 5.0
    assert summary["recent"][0]["comment"] == "Muy buena atención"


async def test_complaint_needs_attention(session):
    contact = await _contact(session)
    result = await feedback.record_feedback(
        session,
        contact.id,
        type="complaint",
        rating=1,
        comment="Llegó tarde",
    )
    assert result["ok"] is True
    assert result["needs_attention"] is True


async def test_invalid_feedback_is_rejected(session):
    contact = await _contact(session)
    for kwargs in (
        {"type": "otro"},
        {"type": "service", "rating": 6},
    ):
        try:
            await feedback.record_feedback(
                session, contact.id, **kwargs
            )
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("Feedback inválido aceptado")


async def test_feedback_tool(session):
    contact = await _contact(session)
    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_record_feedback(
        type="product",
        rating=4,
        comment="Cumplió",
        consent=True,
    )
    assert result["ok"] is True
    summary = await toolbox.tool_get_feedback_summary()
    assert summary["summary"]["count"] == 1


async def test_feedback_request_is_one_per_order_and_due(session):
    contact = await _contact(session)
    cart = Cart(contact_id=contact.id)
    session.add(cart)
    await session.flush()
    order = Order(
        number="WA-FEEDBACK-1",
        contact_id=contact.id,
        cart_id=cart.id,
        status="paid",
        subtotal=100,
        total=100,
        currency="BOB",
    )
    session.add(order)
    await session.commit()

    request = await feedback.create_feedback_request(session, order)
    again = await feedback.create_feedback_request(session, order)
    assert request.id == again.id
    assert request.status == "pending"

    request.scheduled_for = request.scheduled_for.replace(year=2020)
    await session.commit()
    prompt = await feedback.due_feedback_prompt(session, contact.id)
    assert "WA-FEEDBACK-1" in prompt

    result = await feedback.record_feedback(
        session,
        contact.id,
        type="service",
        rating=5,
        order_number="WA-FEEDBACK-1",
    )
    assert result["ok"] is True
    answered = await session.get(FeedbackRequest, request.id)
    assert answered.status == "answered"


async def test_skip_feedback(session):
    contact = await _contact(session)
    cart = Cart(contact_id=contact.id)
    session.add(cart)
    await session.flush()
    order = Order(
        number="WA-FEEDBACK-2",
        contact_id=contact.id,
        cart_id=cart.id,
        status="paid",
        subtotal=100,
        total=100,
        currency="BOB",
    )
    session.add(order)
    await session.commit()
    request = await feedback.create_feedback_request(session, order)
    result = await feedback.skip_feedback(
        session, contact.id, order_number="WA-FEEDBACK-2"
    )
    assert result["ok"] is True
    skipped = await session.get(FeedbackRequest, request.id)
    assert skipped.status == "skipped"


async def test_delivery_and_complaints(session):
    contact = await _contact(session)
    cart = Cart(contact_id=contact.id)
    session.add(cart)
    await session.flush()
    order = Order(
        number="WA-FEEDBACK-3",
        contact_id=contact.id,
        cart_id=cart.id,
        status="paid",
        subtotal=100,
        total=100,
        currency="BOB",
    )
    session.add(order)
    await session.commit()

    delivered = await feedback.mark_delivered(session, "WA-FEEDBACK-3")
    assert delivered["ok"] is True
    pending = await feedback.pending_requests(session)
    assert any(item["order_number"] == "WA-FEEDBACK-3" for item in pending)

    complaint = await feedback.record_feedback(
        session,
        contact.id,
        type="complaint",
        rating=1,
        comment="Llegó tarde",
        order_number="WA-FEEDBACK-3",
    )
    rows = await feedback.complaints(session)
    assert rows
    ack = await feedback.acknowledge(session, complaint["feedback_id"])
    assert ack["ok"] is True
    assert await feedback.complaints(session) == []
