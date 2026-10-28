"""Datos nuevos de VTEX: keywords, tipo, color y material."""

from __future__ import annotations

import pytest

from app.agent import Agent, _atributo_preguntado
from app.models import (
    CatalogItem,
    Contact,
    Conversation,
    ConversationState,
)
from app.services import catalog

ENRIQUECIDO = {
    "specs": {"Material": "Cuerina", "Color": "Plomo"},
    "product_type": "Silla para comedor",
    "color": "Plomo",
    "material": "Cuerina",
    "keywords_source": "vtex",
}


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_detecta_la_pregunta_de_atributo():
    assert _atributo_preguntado("¿de qué color es?") == "color"
    assert _atributo_preguntado("y el material?") == "material"
    assert _atributo_preguntado("qué tipo es") == "tipo"
    assert _atributo_preguntado("¿cuánto sale?") is None


async def _contacto_con_sku(session, wa_id: str, sku: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    session.add(ConversationState(conversation_id=conversacion.id, last_sku=sku))
    await session.commit()
    return contacto


async def test_responde_el_color_del_producto(session):
    session.add(
        CatalogItem(
            sku="VTX-SILLA",
            name="Silla para comedor Cuerina Plomo",
            price=450,
            stock=4,
            category="Sillas",
            brand="MUEBLES",
            attributes=ENRIQUECIDO,
            keywords="Silla para comedor Asiento de comedor",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_sku(session, "59170022001", "VTX-SILLA")

    respuesta = await Agent().handle(session, contacto, "¿de qué color es?")
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "Plomo" in texto


async def test_responde_el_material(session):
    session.add(
        CatalogItem(
            sku="VTX-SILLA-2",
            name="Silla Cuerina Plomo",
            price=450,
            stock=2,
            category="Sillas",
            attributes=ENRIQUECIDO,
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_sku(session, "59170022002", "VTX-SILLA-2")

    respuesta = await Agent().handle(session, contacto, "y el material?")
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "Cuerina" in texto


async def test_sin_dato_ofrece_asesor(session):
    session.add(
        CatalogItem(
            sku="VTX-SIN-DATO",
            name="Producto sin atributos",
            price=100,
            stock=1,
            category="Otros",
            attributes={},
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_sku(session, "59170022003", "VTX-SIN-DATO")

    respuesta = await Agent().handle(session, contacto, "¿de qué color es?")
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "no tengo" in texto
    botones = [
        boton["id"]
        for mensaje in respuesta.messages
        for boton in (mensaje.buttons or [])
    ]
    assert "human" in botones


async def test_el_tipo_ordena_la_busqueda(session):
    session.add_all(
        [
            CatalogItem(
                sku="DISCO-CORTE",
                name="Disco abrasivo de corte para metal",
                price=20,
                stock=10,
                category="Discos",
                attributes={"product_type": "Disco de corte"},
                keywords="disco de corte metal",
                active=True,
            ),
            CatalogItem(
                sku="DISCO-DESB",
                name="Disco abrasivo de desbaste para metal",
                price=25,
                stock=10,
                category="Discos",
                attributes={"product_type": "Disco de desbaste"},
                keywords="disco de desbaste metal",
                active=True,
            ),
        ]
    )
    await session.commit()

    filas = await catalog.search_items(session, "disco para desbastar", limit=2)

    assert filas[0].sku == "DISCO-DESB"
