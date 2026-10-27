"""Casos de la conversación real con Chipi Cedeño (27-oct)."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app.services import conversation_guard


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


async def _contacto(session, wa_id: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def test_dueno_no_se_confunde_con_identidad(session):
    contacto = await _contacto(session, "59170017771")

    respuesta = await Agent().handle(
        session, contacto, "¿quién es el dueño de ROHO Homecenter?"
    )
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "rohi" not in texto, "respondió con su identidad"
    assert "dueños" in texto or "personal" in texto


async def test_juguetes_no_inventa_disponibilidad(session):
    contacto = await _contacto(session, "59170017772")

    for mensaje in ("¿venden juguetes?", "tienen juguetes?"):
        respuesta = await Agent().handle(session, contacto, mensaje)
        texto = " ".join(m.text or "" for m in respuesta.messages).lower()
        assert "no tenemos" in texto
        assert "sí, tenemos" not in texto


async def test_consulta_nueva_no_se_mezcla_con_la_anterior(session):
    session.add(
        CatalogItem(
            sku="TAL-9",
            name="Taladro Percutor 13mm Ingco",
            price=500,
            stock=5,
            category="Taladros",
            brand="INGCO",
            keywords="taladro percutor",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170017773")
    agente = Agent()

    await agente.handle(session, contacto, "¿cuándo empieza el red friday?")
    respuesta = await agente.handle(session, contacto, "tienen taladros?")
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "red" not in texto
    assert "taladro" in texto


def test_ranura_solo_con_la_ultima_pregunta():
    assert conversation_guard.detect_slot(
        "No tengo la fecha del Red Friday. ¿Querés que busque algo más?"
    ) is None
    assert conversation_guard.detect_slot("¿Qué medida necesitás?") == (
        "size",
        "¿Qué medida necesitás?",
    )
