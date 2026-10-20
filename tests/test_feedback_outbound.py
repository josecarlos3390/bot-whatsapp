from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import Cart, Contact, FeedbackRequest, Order
from app.services import feedback, feedback_outbound
from app.whatsapp import Outbound, WhatsAppClient


class FakeWhatsApp:
    def __init__(self):
        self.calls = []

    async def send_template(self, to, name, language="es", parameters=None):
        self.calls.append((to, name, language, parameters))
        return "wamid.test"


def _payload():
    return WhatsAppClient()._payload(
        "59170000000",
        Outbound(
            kind="template",
            template_name="encuesta_atencion",
            template_lang="es",
            template_parameters=["Ana", "WA-1"],
        ),
    )


def test_template_payload():
    payload = _payload()
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "encuesta_atencion"
    assert payload["template"]["language"]["code"] == "es"
    assert payload["template"]["components"][0]["parameters"][0]["text"] == "Ana"


async def test_send_due_surveys(session, monkeypatch):
    monkeypatch.setattr(settings, "feedback_outbound_enabled", True)
    monkeypatch.setattr(settings, "feedback_template_name", "encuesta_atencion")
    contact = Contact(
        wa_id="59170000445",
        phone_e164="+59170000445",
        name="Ana",
        opt_in=True,
    )
    session.add(contact)
    await session.flush()
    cart = Cart(contact_id=contact.id)
    session.add(cart)
    await session.flush()
    order = Order(
        number="WA-OUT-1",
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
    request.scheduled_for = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    wa = FakeWhatsApp()
    result = await feedback_outbound.send_due_surveys(session, wa)
    assert result["sent"] == 1
    assert wa.calls[0][1] == "encuesta_atencion"
    updated = await session.get(FeedbackRequest, request.id)
    assert updated.status == "asked"


async def test_send_due_disabled(session):
    result = await feedback_outbound.send_due_surveys(
        session, FakeWhatsApp()
    )
    assert result["sent"] == 0
