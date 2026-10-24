from __future__ import annotations

from app.agent import Agent
from app.config import settings
from app.models import CatalogItem, Contact, ProductImage
from app.services import catalog
from app.whatsapp import Outbound, WhatsAppClient


def test_image_payload():
    payload = WhatsAppClient()._payload(
        "59170000000",
        Outbound(
            kind="image",
            url="https://cdn.example.com/x.jpg",
            text="Producto",
        ),
    )
    assert payload["type"] == "image"
    assert payload["image"]["link"].startswith("https://")
    assert payload["image"]["caption"] == "Producto"


async def test_primary_image_and_product_detail(session):
    session.add(
        CatalogItem(
            sku="IMG-1",
            name="PRODUCTO CON IMAGEN",
            category="Filtros",
            price=100,
            stock=2,
        )
    )
    session.add(
        ProductImage(
            sku="IMG-1",
            url="https://cdn.example.com/img-1.jpg",
            alt="Producto",
            position=1,
            is_primary=True,
            approved=True,
        )
    )
    contact = Contact(wa_id="59170000888", phone_e164="+59170000888")
    session.add(contact)
    await session.commit()

    assert (
        await catalog.primary_image(session, "IMG-1")
        == "https://cdn.example.com/img-1.jpg"
    )
    info = await catalog.primary_image_info(session, "IMG-1")
    assert info is not None and info["source"] is None

    reply = await Agent().handle(session, contact, "product:IMG-1")
    assert reply.messages[0].kind == "image"
    # La ficha ofrece las acciones como lista (agregar 1/2/3 + salidas).
    assert reply.messages[1].kind == "list"
    assert reply.messages[1].sections[0]["rows"]


async def test_placeholder_image(session, monkeypatch):
    monkeypatch.setattr(
        settings,
        "product_image_placeholder",
        "https://cdn.example.com/placeholder.jpg",
    )
    session.add(
        CatalogItem(
            sku="IMG-2",
            name="PRODUCTO SIN FOTO",
            category="Filtros",
            price=100,
            stock=2,
        )
    )
    contact = Contact(wa_id="59170000889", phone_e164="+59170000889")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "product:IMG-2")
    assert reply.messages[0].kind == "image"
    assert reply.messages[0].text == "Imagen referencial"


async def test_demo_image_is_marked_referential(session):
    session.add(
        CatalogItem(
            sku="IMG-3",
            name="PRODUCTO DEMO",
            category="Filtros",
            price=100,
            stock=2,
        )
    )
    session.add(
        ProductImage(
            sku="IMG-3",
            url="https://placehold.co/600x600/EEEEEE/333333/png?text=Filtros",
            source="demo",
            is_primary=True,
            approved=True,
        )
    )
    contact = Contact(wa_id="59170000890", phone_e164="+59170000890")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "product:IMG-3")
    assert reply.messages[0].text == "Imagen referencial"
