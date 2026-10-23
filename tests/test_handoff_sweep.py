"""Barrido de handoffs y "escribiendo…" en WhatsApp."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models import Contact, Conversation, Handoff
from app.services import handoffs
from app.whatsapp import WhatsAppClient


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"messages": [{"id": "wamid.test"}]}


class FakeHTTP:
    def __init__(self):
        self.payload = None

    async def post(self, url, headers=None, json=None):
        self.payload = json
        return FakeResponse()


async def _conversation(session, wa_id: str):
    contact = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    return contact, conversation


async def test_barrido_cierra_pendientes_vencidos(session):
    contact, conversation = await _conversation(session, "59170000971")
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Pidió un asesor"
    )
    handoff.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await session.commit()

    result = await handoffs.sweep_stale_handoffs(
        session, pending_minutes=5, taken_minutes=120
    )

    assert result["resolved"] == 1
    assert (await session.get(Handoff, handoff.id)).status == "resolved"
    assert conversation.bot_paused is False


async def test_barrido_no_toca_casos_recientes(session):
    contact, conversation = await _conversation(session, "59170000972")
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Recién pedido"
    )

    result = await handoffs.sweep_stale_handoffs(
        session, pending_minutes=5, taken_minutes=120
    )

    assert result["resolved"] == 0
    assert (await session.get(Handoff, handoff.id)).status == "pending"


async def test_barrido_cierra_caso_tomado_y_abandonado(session):
    contact, conversation = await _conversation(session, "59170000973")
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Pidió un asesor"
    )
    await handoffs.take_handoff(session, handoff.id, "Ana")
    handoff.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    await session.commit()

    result = await handoffs.sweep_stale_handoffs(
        session, pending_minutes=5, taken_minutes=120
    )

    assert result["resolved"] == 1
    assert conversation.bot_paused is False


async def test_mark_read_envia_typing(monkeypatch):
    monkeypatch.setattr(settings, "wa_dry_run", False)
    monkeypatch.setattr(settings, "wa_access_token", "token")
    monkeypatch.setattr(settings, "wa_phone_number_id", "123456")

    client = WhatsAppClient()
    fake = FakeHTTP()
    client._client = fake  # type: ignore[assignment]

    assert await client.mark_read("wamid.ABC") is True
    assert fake.payload["status"] == "read"
    assert fake.payload["message_id"] == "wamid.ABC"
    assert fake.payload["typing_indicator"] == {"type": "text"}


async def test_mark_read_no_falla_sin_token(monkeypatch):
    monkeypatch.setattr(settings, "wa_access_token", "")

    client = WhatsAppClient()
    assert await client.mark_read("wamid.ABC") is False
