"""«Es caro»: el bot ofrece algo más barato del mismo rubro."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation, Message
from app.services import objecion


def test_detecta_la_objecion():
    for texto in (
        "es muy caro",
        "está caro",
        "carísimo",
        "no me alcanza",
        "fuera de presupuesto",
        "muy costoso",
    ):
        assert objecion.es_objecion(texto), texto


def test_no_confunde_una_consulta_normal():
    assert not objecion.es_objecion("busco una mesa")
    assert not objecion.es_objecion("¿tienen stock?")


async def _contacto_con_producto(session, sku: str) -> Contact:
    contacto = Contact(
        wa_id="59170033001", phone_e164="+59170033001", name="Ana"
    )
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversacion.id,
            direction="in",
            type="text",
            text=f"product:{sku}",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return contacto


async def test_ofrece_alternativas_mas_baratas(session):
    session.add_all(
        [
            CatalogItem(
                sku="OBJ-CARO",
                name="Mesa Cara",
                price="4000",
                stock=2,
                brand="TEST",
                category="Mesas",
                active=True,
            ),
            CatalogItem(
                sku="OBJ-BARATA",
                name="Mesa Barata",
                price="900",
                stock=5,
                brand="TEST",
                category="Mesas",
                active=True,
            ),
        ]
    )
    await session.commit()
    contacto = await _contacto_con_producto(session, "OBJ-CARO")

    respuesta = await Agent().handle(session, contacto, "es muy caro")

    texto = " ".join(m.text or "" for m in respuesta.messages)
    assert "más económicas" in texto
    assert "Mesa Barata" in texto
    assert "4.000" in texto


async def test_sin_alternativa_ofrece_otra_categoria(session):
    session.add(
        CatalogItem(
            sku="OBJ-SOLO",
            name="Mesa Única",
            price="5000",
            stock=1,
            brand="TEST",
            category="Mesas",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_producto(session, "OBJ-SOLO")

    respuesta = await Agent().handle(session, contacto, "es caro")

    mensaje = respuesta.messages[0]
    assert "Te entiendo" in (mensaje.text or "")
    ids = [boton["id"] for boton in mensaje.buttons]
    assert "human" in ids
