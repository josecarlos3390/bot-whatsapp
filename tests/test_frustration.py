"""Frustración: disculpa + derivación, nunca venta."""

from __future__ import annotations

from sqlalchemy import select

from app.agent import Agent, AgentReply, Outbound
from app.models import Contact, Conversation, Handoff
from app.services import intent, output_guard


def test_detecta_enojo_y_espera():
    assert intent.rules("Esto es una estafa, nadie me atiende!!")["frustrated"]
    assert intent.rules("hace una hora esperando respuesta")["frustrated"]
    assert not intent.rules("quiero un colchón")["frustrated"]


async def test_enojo_disculpa_y_deriva(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000881", phone_e164="+59170000881")
    session.add(contact)
    await session.flush()
    session.add(Conversation(contact_id=contact.id))
    await session.commit()

    reply = await Agent().handle(
        session, contact, "Esto es una estafa, nadie me atiende!!"
    )

    texto = " ".join(m.text or "" for m in reply.messages)
    assert "disculpas" in texto.lower()
    assert "persona del equipo" in texto.lower()

    handoff = await session.scalar(
        select(Handoff).where(Handoff.status.in_(("pending", "queued")))
    )
    assert handoff is not None


async def test_guard_quita_venta_a_cliente_enojado(session):
    reply = AgentReply(
        [
            Outbound(
                kind="image", url="https://cdn.example.com/x.png", text="TV"
            ),
            Outbound(
                kind="list",
                text="Mirá estas opciones",
                sections=[
                    {
                        "title": "Opciones",
                        "rows": [
                            {
                                "id": "product:TV-1",
                                "title": "TV 32",
                                "description": "Bs 1.599",
                            }
                        ],
                    }
                ],
            ),
            Outbound(text="Te pido disculpas por la espera."),
        ]
    )

    result = await output_guard.sanitize(
        session, reply, "hace una hora esperando respuesta!!"
    )

    assert all(m.kind != "image" for m in result.messages)
    assert not any(
        str(row.get("id", "")).startswith("product:")
        for message in result.messages
        for section in (message.sections or [])
        for row in section.get("rows") or []
    )
    assert any("disculpas" in (m.text or "").lower() for m in result.messages)
