"""El atributo del cliente manda: 'espejos redondos' no puede dar cuadrados."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation


@pytest.fixture
async def espejos(session):
    session.add_all(
        [
            CatalogItem(
                sku="ESP-RED",
                name="Espejo Camelia Redondo 70 Astra",
                price=499,
                stock=10,
                category="Muebles de baño",
                brand="ASTRA",
                keywords="espejo redondo",
                active=True,
            ),
            CatalogItem(
                sku="ESP-CUA",
                name="Espejo Bisotê 80X85 Negro Cozimax",
                price=629,
                stock=10,
                category="Muebles de baño",
                brand="COZIMAX",
                keywords="espejo rectangular",
                active=True,
            ),
        ]
    )
    await session.commit()
    return session


async def test_espejos_redondos_devuelve_redondos(espejos, monkeypatch):
    from app.config import settings

    # Fuerza el camino semántico: la búsqueda literal debe ganar igual.
    monkeypatch.setattr(settings, "deepseek_api_key", "test")

    contacto = Contact(wa_id="59170017771", phone_e164="+59170017771")
    espejos.add(contacto)
    await espejos.flush()
    espejos.add(Conversation(contact_id=contacto.id))
    await espejos.commit()

    respuesta = await Agent()._semantic_reply(
        espejos, contacto, "espejos redondos"
    )

    assert respuesta is not None
    textos = " ".join(mensaje.text or "" for mensaje in respuesta.messages)
    assert "Camelia" in textos
    assert "Bisot" not in textos
