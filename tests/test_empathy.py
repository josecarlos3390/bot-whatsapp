"""Empatía: los temas delicados no se responden con productos."""

from __future__ import annotations

from app.agent import Agent
from app.models import Contact
from app.services import intent


def test_detecta_tristeza_y_duelo():
    triste = intent.rules("Estoy triste")
    duelo = intent.rules("Murió mi mascota, por eso estoy triste")

    assert triste["sensitive"] is True
    assert triste["sensitive_topic"] == "animo"
    assert duelo["sensitive"] is True
    assert duelo["sensitive_topic"] == "duelo"


def test_consulta_de_producto_no_es_sensible():
    assert intent.rules("quiero un colchón de 2 plazas")["sensitive"] is False


async def test_estoy_triste_recibe_empatia_sin_productos(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000861", phone_e164="+59170000861")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "Estoy triste")

    texto = " ".join(m.text or "" for m in reply.messages)
    assert "mal que estés así" in texto.lower()
    # Nada de productos ni de "qué bueno".
    assert "qué bueno" not in texto.lower()
    assert all(m.kind != "image" for m in reply.messages)
    assert all(
        not any(str(row.get("id", "")).startswith("product:") for row in (m.sections[0]["rows"] if m.sections else []))
        for m in reply.messages
    )


async def test_duelo_recibe_lamento_y_derivacion(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000862", phone_e164="+59170000862")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(
        session, contact, "Murió mi mascota, por eso estoy triste"
    )

    texto = " ".join(m.text or "" for m in reply.messages)
    assert "lamento" in texto.lower()
    assert "mascota" in texto.lower()
    assert all(m.kind != "image" for m in reply.messages)
    botones = [
        button["id"]
        for message in reply.messages
        for button in (message.buttons or [])
    ]
    assert "human" in botones
