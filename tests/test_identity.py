"""Preguntas básicas: identidad y pequeña charla no deben buscar productos."""

from __future__ import annotations

from app.agent import Agent
from app.models import Contact, Conversation


async def _contacto(session, wa_id: str) -> Contact:
    contact = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contact)
    await session.flush()
    session.add(Conversation(contact_id=contact.id))
    await session.commit()
    return contact


def _texto(reply) -> str:
    return " ".join(message.text or "" for message in reply.messages).lower()


async def test_quien_eres_responde_identidad(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = await _contacto(session, "59170001301")

    reply = await Agent().handle(session, contact, "Quien eres?")

    texto = _texto(reply)
    assert "rohi" in texto
    assert "asesora" in texto
    assert all(message.kind != "image" for message in reply.messages)


async def test_no_toma_la_identidad_como_respuesta_pendiente(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    agent = Agent()
    contact = await _contacto(session, "59170001302")

    # Primero una búsqueda amplia: deja una pregunta pendiente.
    await agent.handle(session, contact, "busco colchones")
    # Después una pregunta de identidad: no debe buscar "quien eres".
    reply = await agent.handle(session, contact, "quien eres?")

    texto = _texto(reply)
    assert "rohi" in texto
    assert "quien eres" not in texto
    assert all(message.kind != "image" for message in reply.messages)


async def test_que_podes_hacer_responde_capacidades(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = await _contacto(session, "59170001303")

    reply = await Agent().handle(session, contact, "que podes hacer?")

    assert "rohi" in _texto(reply)
