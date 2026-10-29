"""«Mostrame las más elegidas»: respuesta concreta, no un «no tengo»."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import (
    CatalogItem,
    Contact,
    Conversation,
    ConversationState,
    ProductSalesStat,
)
from app.services import most_chosen


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_reconoce_las_formas_de_pedirlo():
    assert most_chosen.is_most_chosen("mostrame las mas elegidas")
    assert most_chosen.is_most_chosen("y las más elegidas?")
    assert most_chosen.is_most_chosen("mostrame las populares")
    assert most_chosen.is_most_chosen("lo más vendido")


def test_no_confunde_una_busqueda_de_producto():
    assert not most_chosen.is_most_chosen("busco un colchón de 2 plazas")
    assert not most_chosen.is_most_chosen("tenés televisores?")


async def _contacto_con_rubro(session, wa_id: str, rubro: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    session.add(
        ConversationState(conversation_id=conversacion.id, category=rubro)
    )
    await session.commit()
    return contacto


async def test_sin_rubro_pregunta_cual(session):
    contacto = await _contacto_con_rubro(session, "59170030001", "")

    respuesta = await most_chosen.reply(
        Agent(), session, contacto, "mostrame las más elegidas"
    )

    assert respuesta is not None
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()
    assert "de qué rubro" in texto or "de que rubro" in texto


async def test_usa_las_ventas_cuando_existen(session):
    session.add_all(
        [
            CatalogItem(
                sku="MAS-1",
                name="Colchón Uno 2 Plazas",
                price=1000,
                stock=3,
                category="Colchones",
                image_url="https://example.com/1.png",
                active=True,
            ),
            CatalogItem(
                sku="MAS-2",
                name="Colchón Dos 2 Plazas",
                price=1200,
                stock=9,
                category="Colchones",
                image_url="https://example.com/2.png",
                active=True,
            ),
        ]
    )
    session.add_all(
        [
            ProductSalesStat(sku="MAS-1", units_30d=9),
            ProductSalesStat(sku="MAS-2", units_30d=1),
        ]
    )
    await session.commit()
    contacto = await _contacto_con_rubro(session, "59170030002", "colchon")

    respuesta = await most_chosen.reply(
        Agent(), session, contacto, "mostrame las más elegidas"
    )
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "más vendidas" in texto
    assert "Colchón Uno" in texto


async def test_sin_ventas_lo_dice_y_muestra_por_descuento(session):
    session.add(
        CatalogItem(
            sku="MAS-3",
            name="Colchón Tres 2 Plazas",
            price=900,
            stock=4,
            category="Colchones",
            image_url="https://example.com/3.png",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_rubro(session, "59170030003", "colchon")

    respuesta = await most_chosen.reply(
        Agent(), session, contacto, "mostrame las más elegidas"
    )
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "no tengo el ranking" in texto.lower()
    assert "Colchón Tres" in texto
