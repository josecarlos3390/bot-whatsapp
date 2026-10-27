from __future__ import annotations

import pytest

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Contact, Conversation, Handoff, Message
from app.services import handoffs

@pytest.fixture(autouse=True)
def _horario_abierto(monkeypatch):
    """Las pruebas no dependen de la hora real del servidor."""
    from app.config import settings

    monkeypatch.setattr(settings, "office_hours_enabled", False)


async def _asesor_online(session, nombre: str = "Ana"):
    """Crea (o marca) un asesor conectado, con tope de 5 casos."""
    from app.models import Advisor
    from app.services import advisors as advisor_service

    fila = await session.scalar(select(Advisor).where(Advisor.username == "ana"))
    if fila is None:
        fila = await advisor_service.create_advisor(
            session,
            username="ana",
            display_name=nombre,
            password="clave12345",
            role="agent",
        )
    fila.last_seen_at = datetime.now(timezone.utc)
    fila.on_duty = True
    fila.max_cases = 5
    await session.commit()
    return fila



class FakeWhatsApp:
    async def send_text(self, to, text):
        self.last = (to, text)
        return "wamid.handoff"


class FailingWhatsApp:
    async def send_text(self, to, text):
        raise RuntimeError("131030 recipient not allowed")


async def test_create_take_resolve_handoff(session):
    await _asesor_online(session)
    contact = Contact(wa_id="59170000991", phone_e164="+59170000991")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()

    handoff, notification = await handoffs.create_handoff(
        session, conversation, contact, "Quiere hablar con alguien"
    )
    assert notification["ok"] is True
    assert handoff.status == "pending"
    # Mientras el caso espera, el bot sigue atendiendo.
    assert conversation.bot_paused is False

    again, _ = await handoffs.create_handoff(
        session, conversation, contact, "Otra vez"
    )
    assert again.id == handoff.id

    rows = await handoffs.list_handoffs(session, status="pending")
    assert rows and rows[0]["id"] == handoff.id

    taken = await handoffs.take_handoff(session, handoff.id, "Ana")
    assert taken["ok"] is True
    # Cuando un asesor toma el caso, el bot se calla.
    assert conversation.bot_paused is True

    resolved = await handoffs.resolve_handoff(
        session, handoff.id, notes="Resuelto"
    )
    assert resolved["ok"] is True
    assert (await session.get(Handoff, handoff.id)).status == "resolved"
    assert conversation.bot_paused is False


async def test_tomar_envia_saludo_del_asesor(session):
    contact = Contact(
        wa_id="59170000994", phone_e164="+59170000994", name="Lucía"
    )
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Quiere un asesor"
    )

    fake = FakeWhatsApp()
    result = await handoffs.take_handoff(
        session, handoff.id, "Ana Pérez", whatsapp=fake
    )

    assert result["ok"] is True
    assert fake.last is not None
    assert "Ana Pérez" in fake.last[1]
    assert "Lucía" in fake.last[1]

    # El saludo queda en el historial, así la consola lo muestra.
    saved = await session.scalar(
        select(Message).where(Message.conversation_id == conversation.id)
    )
    assert saved is not None and "Ana Pérez" in (saved.text or "")


async def test_resolver_avisa_al_cliente(session):
    contact = Contact(wa_id="59170000993", phone_e164="+59170000993")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Consulta de factura"
    )
    await handoffs.take_handoff(session, handoff.id, "Ana")

    fake = FakeWhatsApp()
    await handoffs.resolve_handoff(
        session, handoff.id, notes="Se emitió la factura", whatsapp=fake
    )

    assert conversation.bot_paused is False
    assert fake.last is not None
    assert "resuelto" in fake.last[1].lower()


async def test_handoff_auto_assigns_on_duty(session):
    from app.services import advisors

    await advisors.create_advisor(session, "guardia", "clave", "Guardia")
    contact = Contact(wa_id="59170000995", phone_e164="+59170000995")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()
    # El asesor queda de guardia.
    from app.models import Advisor

    advisor = await session.scalar(
        select(Advisor).where(Advisor.username == "guardia")
    )
    advisor.on_duty = True
    # Solo queda conectado el asesor de guardia.
    for otro in (await session.scalars(select(Advisor))).all():
        otro.last_seen_at = None
    advisor.last_seen_at = datetime.now(timezone.utc)
    await session.commit()

    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Necesita ayuda"
    )
    assert handoff.assigned_to == "Guardia"


async def test_unattended_handoff_auto_resumes(session):
    contact = Contact(wa_id="59170000994", phone_e164="+59170000994")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id, bot_paused=True)
    session.add(conversation)
    await session.commit()
    handoff = Handoff(
        conversation_id=conversation.id,
        reason="Sin asesor",
        status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    )
    session.add(handoff)
    await session.commit()

    resumed = await handoffs.resume_if_unattended(
        session, conversation, timeout_minutes=15
    )
    assert resumed is True
    assert conversation.bot_paused is False
    await session.refresh(handoff)
    assert handoff.status == "resolved"


async def test_reply_handoff_stores_message(session):
    contact = Contact(wa_id="59170000992", phone_e164="+59170000992")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()
    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Asesor"
    )

    wa = FakeWhatsApp()
    result = await handoffs.reply_handoff(
        session, handoff.id, "Te ayudo por acá", wa
    )
    assert result["ok"] is True
    assert wa.last == ("59170000992", "Te ayudo por acá")


async def test_reply_failure_is_reported(session):
    contact = Contact(wa_id="59170000997", phone_e164="+59170000997")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()
    handoff, _ = await handoffs.create_handoff(
        session, conversation, contact, "Asesor"
    )

    result = await handoffs.reply_handoff(
        session, handoff.id, "No permitido", FailingWhatsApp()
    )
    assert result["ok"] is False
    assert result["reason"] == "send_failed"
