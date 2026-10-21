"""Búsqueda por código de barra."""

from __future__ import annotations

from app.agent import Agent
from app.models import CatalogItem, Contact
from app.services import catalog


async def test_extrae_codigo_de_barra_del_mensaje():
    assert catalog.barcode_from_text("tienen el 8435771900983?") == "8435771900983"
    assert catalog.barcode_from_text("2 plazas") is None
    assert catalog.barcode_from_text("codigo 22007119") == "22007119"


async def test_busca_por_codigo_de_barra(session):
    session.add(
        CatalogItem(
            sku="BAR-1",
            name="ASPIRADOR DE COLCHONES",
            price=2169,
            stock=3,
            barcode="8435771900983",
            active=True,
        )
    )
    await session.commit()

    found = await catalog.get_by_barcode(session, "8435771900983")
    assert found is not None and found.sku == "BAR-1"

    assert await catalog.get_by_barcode(session, "123") is None


async def test_el_bot_responde_por_codigo_de_barra(session):
    session.add(
        CatalogItem(
            sku="BAR-2",
            name="ASPIRADOR DE COLCHONES 0.5L",
            price=2169,
            stock=4,
            barcode="4054278975122",
            active=True,
        )
    )
    await session.commit()

    contact = Contact(wa_id="59170000901", phone_e164="+59170000901", name="Ana")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "tienen el 4054278975122?")

    text = " ".join(m.text for m in reply.messages if m.text)
    assert "ASPIRADOR" in text


async def test_codigo_inexistente_no_rompe(session):
    contact = Contact(wa_id="59170000902", phone_e164="+59170000902", name="Ana")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "buscar 9999999999999")

    assert reply.messages
