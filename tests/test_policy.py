"""Guardrails de política: derivar sin improvisar."""

from __future__ import annotations

from app.agent import Agent, AgentReply, Outbound
from app.models import Contact, Conversation
from app.services import output_guard, policy


def test_detecta_temas_sensibles_de_politica():
    assert policy.detect("¿qué remedio tomo para el dolor?") == "salud"
    assert policy.detect("quiero demandar a la tienda") == "legal"
    assert policy.detect("¿puedo sacar un crédito?") == "financiero"
    assert policy.detect("pasame el número de tarjeta") == "datos"
    assert policy.detect("necesito la conexión de gas") == "seguridad"


def test_no_confunde_interes_con_financiero():
    assert policy.detect("me interesa el colchón de 2 plazas") is None


async def test_consulta_medica_se_deriva(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000921", phone_e164="+59170000921")
    session.add(contact)
    await session.flush()
    session.add(Conversation(contact_id=contact.id))
    await session.commit()

    reply = await Agent().handle(
        session, contact, "¿qué remedio tomo para el dolor de espalda?"
    )

    texto = " ".join(m.text or "" for m in reply.messages).lower()
    assert "no doy consejos de salud" in texto
    botones = [
        button["id"]
        for message in reply.messages
        for button in (message.buttons or [])
    ]
    assert "human" in botones


async def test_guard_quita_productos_en_tema_legal(session):
    reply = AgentReply(
        [
            Outbound(
                kind="image", url="https://cdn.example.com/x.png", text="TV"
            ),
            Outbound(text="Te paso el dato del abogado."),
        ]
    )

    result = await output_guard.sanitize(
        session, reply, "quiero demandar a la tienda"
    )

    assert all(message.kind != "image" for message in result.messages)
    assert any("legal" in (m.text or "").lower() for m in result.messages)
