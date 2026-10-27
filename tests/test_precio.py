"""Pedidos de precio: 'los más baratos' debe listar artículos con precio."""

from __future__ import annotations

import pytest

from app.agent import Agent, _price_intent
from app.models import CatalogItem, Contact, Conversation


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


@pytest.fixture
async def taladros(session):
    session.add_all(
        [
            CatalogItem(
                sku="TAL-CARO",
                name="Taladro Percutor Bosch 800W",
                price=2986,
                stock=5,
                category="Taladros",
                brand="BOSCH",
                keywords="taladro percutor",
                image_url="https://example.com/taladro-bosch.jpg",
                active=True,
            ),
            CatalogItem(
                sku="TAL-BARATO",
                name="Taladro Atornillador Ingco 12V",
                price=164,
                stock=5,
                category="Taladros",
                brand="INGCO",
                keywords="taladro atornillador",
                image_url="https://example.com/taladro-ingco.jpg",
                active=True,
            ),
            CatalogItem(
                sku="TAL-MEDIO",
                name="Taladro Electrico Ingco 550W",
                price=370,
                stock=5,
                category="Taladros",
                brand="INGCO",
                keywords="taladro electrico",
                image_url="https://example.com/taladro-electrico.jpg",
                active=True,
            ),
        ]
    )
    await session.commit()
    return session


def test_detecta_pedido_de_precio():
    assert _price_intent("quiero los mas baratos") == "asc"
    assert _price_intent("cual es el que tiene el precio mas bajo") == "asc"
    assert _price_intent("mostrame el mas caro") == "desc"
    assert _price_intent("busco un taladro") is None


async def test_los_mas_baratos_listan_precios(taladros):
    contacto = Contact(wa_id="59170016661", phone_e164="+59170016661")
    taladros.add(contacto)
    await taladros.flush()
    taladros.add(Conversation(contact_id=contacto.id))
    await taladros.commit()
    agente = Agent()

    await agente.handle(taladros, contacto, "tienes taladros?")
    respuesta = await agente.handle(taladros, contacto, "quiero los mas baratos")

    texto = " ".join(mensaje.text or "" for mensaje in respuesta.messages).lower()
    assert "más baratos" in texto
    # El primero que se muestra es el de menor precio.
    primero = next(
        mensaje.text for mensaje in respuesta.messages if mensaje.kind == "image"
    )
    assert "164" in primero


async def test_el_mas_barato_devuelve_uno_solo(taladros):
    contacto = Contact(wa_id="59170016662", phone_e164="+59170016662")
    taladros.add(contacto)
    await taladros.flush()
    taladros.add(Conversation(contact_id=contacto.id))
    await taladros.commit()
    agente = Agent()

    await agente.handle(taladros, contacto, "tienes taladros?")
    respuesta = await agente.handle(
        taladros, contacto, "cual es el que tiene el precio mas bajo"
    )

    imagenes = [m for m in respuesta.messages if m.kind == "image"]
    assert len(imagenes) == 1
    assert "164" in (imagenes[0].text or "")
