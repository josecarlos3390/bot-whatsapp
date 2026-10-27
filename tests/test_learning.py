"""Aprendizaje de búsquedas: lo que no encontraba, se recuerda."""

from __future__ import annotations

import pytest

from app.models import CatalogItem, Contact, Conversation, QueryLearning
from app.services import learning


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


async def test_normaliza_el_termino():
    assert learning.normalize("  Taladros?! ") == "taladros"
    assert learning.normalize("PERFORADORA") == "perforadora"


async def test_recuerda_y_cuenta(session):
    await learning.remember(
        session, term="perforadora", query="taladro percutor", producto="taladro"
    )

    assert await learning.recall(session, "perforadora") == "taladro percutor"
    assert await learning.recall(session, "perforadora") == "taladro percutor"

    fila = await session.scalar(
        QueryLearning.__table__.select().where(QueryLearning.term == "perforadora")
    )
    assert fila is not None


async def test_registra_lo_que_no_encuentra(session):
    await learning.record_miss(session, "alfombra voladora")
    await learning.record_miss(session, "alfombra voladora")

    resumen = await learning.summary(session)
    assert resumen["pendientes"] == 1
    assert resumen["top_pendientes"][0]["term"] == "alfombra voladora"
    assert resumen["top_pendientes"][0]["misses"] == 2


async def test_resuelve_con_ia_y_aprende(session, monkeypatch):
    from app.agent import Agent
    from app.config import settings
    from app.services import understanding

    monkeypatch.setattr(settings, "deepseek_api_key", "test")

    session.add(
        CatalogItem(
            sku="TAL-13",
            name="Taladro Percutor 13mm Ingco",
            price=500,
            stock=5,
            category="Taladros",
            brand="INGCO",
            keywords="taladro percutor",
            image_url="https://example.com/taladro.jpg",
            active=True,
        )
    )
    await session.commit()

    contacto = Contact(wa_id="59170015551", phone_e164="+59170015551")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    async def falso_parse(_client, _text):
        return {
            "intencion": "producto",
            "producto": "taladro",
            "atributos": ["percutor", "13mm"],
            "orden_precio": None,
            "referencia": None,
        }

    monkeypatch.setattr(understanding, "parse", falso_parse)

    agente = Agent()
    primera = await agente._search_reply(session, contacto, "perforadora")

    textos = " ".join(m.text or "" for m in primera.messages)
    assert "Taladro Percutor" in textos

    # Queda aprendido: la segunda vez no necesita el modelo.
    async def sin_modelo(_client, _text):
        raise AssertionError("no debería consultar la IA de nuevo")

    monkeypatch.setattr(understanding, "parse", sin_modelo)
    segunda = await agente._search_reply(session, contacto, "perforadora")

    textos2 = " ".join(m.text or "" for m in segunda.messages)
    assert "Taladro Percutor" in textos2
