"""El bot recuerda lo último que vio el cliente."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation, Message
from app.services import memoria_cliente


async def _contacto_con_visto(session, sku: str, dias: int = 1) -> Contact:
    contacto = Contact(
        wa_id="59170032001", phone_e164="+59170032001", name="JoseKa"
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
            created_at=datetime.now(timezone.utc) - timedelta(days=dias),
        )
    )
    await session.commit()
    return contacto


async def test_recuerda_el_ultimo_producto(session):
    session.add(
        CatalogItem(
            sku="MEM-001",
            name="Sofá Acapulco",
            price="7990",
            stock=2,
            brand="TEST",
            category="Sala",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_visto(session, "MEM-001")

    visto = await memoria_cliente.ultimo_visto(session, contacto)

    assert visto is not None
    assert visto["sku"] == "MEM-001"
    assert "Acapulco" in visto["name"]


async def test_lo_viejo_no_se_recuerda(session):
    session.add(
        CatalogItem(
            sku="MEM-002",
            name="Sofá Viejo",
            price="1000",
            stock=1,
            brand="TEST",
            category="Sala",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_visto(session, "MEM-002", dias=40)

    assert await memoria_cliente.ultimo_visto(session, contacto) is None


async def test_saludo_sin_historial_es_normal(session):
    contacto = Contact(
        wa_id="59170032002", phone_e164="+59170032002", name="Nuevo"
    )
    session.add(contacto)
    await session.commit()

    assert (
        await memoria_cliente.saludo_con_memoria(Agent(), session, contacto)
        is None
    )


async def test_el_saludo_trae_boton_para_retomar(session):
    session.add(
        CatalogItem(
            sku="MEM-003",
            name="Sillón Nórdico",
            price="2500",
            stock=5,
            brand="TEST",
            category="Sala",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto_con_visto(session, "MEM-003")

    respuesta = await Agent().handle(session, contacto, "hola")

    texto = respuesta.messages[0].text or ""
    assert "La última vez viste" in texto
    assert "2.500" in texto
    ids = [boton["id"] for boton in respuesta.messages[0].buttons]
    assert "product:MEM-003" in ids
