from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.config import settings
from app.models import CartItem, Contact, ProductPromotion
from app.services import catalog, native_commerce
from app.services.ingest import ingest_inbound
from app.agent import Toolbox
from app.whatsapp import Outbound, WhatsAppClient, extract_order


def test_parse_native_order():
    order = native_commerce.parse_order(
        {
            "order": {
                "catalog_id": "cat-1",
                "text": "mi pedido",
                "product_items": [
                    {"product_retailer_id": "filt-001", "quantity": 2}
                ],
            }
        }
    )
    assert order.catalog_id == "cat-1"
    assert order.items[0].sku == "FILT-001"
    assert order.items[0].quantity == 2


def test_extract_order():
    assert extract_order({"type": "order", "order": {"product_items": []}}) == {
        "product_items": []
    }
    assert extract_order({"type": "text"}) is None


async def test_add_native_order_to_cart(session):
    contact = Contact(wa_id="59170000555", phone_e164="+59170000555")
    session.add(contact)
    await session.commit()

    order = native_commerce.parse_order(
        {
            "order": {
                "product_items": [
                    {"product_retailer_id": "FILT-001", "quantity": 2}
                ]
            }
        }
    )
    summary, errors = await native_commerce.add_order_to_cart(
        session, contact, order
    )
    assert not errors
    assert summary["count"] == 2
    text = native_commerce.summary_text(summary)
    assert "FILT-001" in text or "Filtro" in text


async def test_ingest_native_order(session):
    result = await ingest_inbound(
        session,
        wa_id="59170000556",
        text="",
        wa_message_id="wamid.native.1",
        name="Native",
        deliver=False,
        order={
            "catalog_id": "cat-1",
            "product_items": [
                {"product_retailer_id": "FILT-001", "quantity": 1}
            ],
        },
    )
    assert result
    assert "pedido" in result[0]["text"].lower()
    contact = await session.scalar(
        select(Contact).where(Contact.wa_id == "59170000556")
    )
    count = await session.scalar(
        select(CartItem).where(CartItem.cart_id.is_not(None))
    )
    assert contact is not None
    assert count is not None


def test_native_payloads():
    client = WhatsAppClient()
    catalog = client._payload(
        "59170000000",
        Outbound(kind="catalog", text="Catálogo", catalog_id="cat-1"),
    )
    assert catalog["interactive"]["type"] == "catalog_message"

    product = client._payload(
        "59170000000",
        Outbound(
            kind="product",
            text="Producto",
            catalog_id="cat-1",
            product_retailer_id="FILT-001",
        ),
    )
    assert product["interactive"]["action"]["product_retailer_id"] == "FILT-001"

    product_list = client._payload(
        "59170000000",
        Outbound(
            kind="product_list",
            text="Lista",
            catalog_id="cat-1",
            sections=[
                {
                    "title": "Filtros",
                    "product_items": [{"product_retailer_id": "FILT-001"}],
                }
            ],
        ),
    )
    assert product_list["interactive"]["action"]["catalog_id"] == "cat-1"


def test_native_ready_flags(monkeypatch):
    monkeypatch.setattr(settings, "wa_native_catalog_enabled", True)
    monkeypatch.setattr(settings, "wa_catalog_id", "cat-1")
    monkeypatch.setattr(settings, "wa_access_token", "token")
    monkeypatch.setattr(settings, "wa_phone_number_id", "phone")
    assert native_commerce.is_ready() is True
    monkeypatch.setattr(settings, "wa_native_cart_enabled", True)
    assert native_commerce.cart_ready() is True


async def test_search_fallback_without_discount(session):
    contact = Contact(wa_id="59170000558", phone_e164="+59170000558")
    session.add(contact)
    await session.commit()
    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_search_products(
        category="Filtros", only_discount=True
    )
    assert result["ok"] is True
    assert result["fallback_without_discount"] is True
    assert result["products"]


async def test_search_filters_and_native_catalog(session, monkeypatch):
    contact = Contact(wa_id="59170000557", phone_e164="+59170000557")
    session.add(contact)
    session.add(
        ProductPromotion(
            sku="FILT-001",
            price=50,
            discount_percent=41.18,
            valid_from=date.today() - timedelta(days=1),
            valid_to=date.today() + timedelta(days=10),
            tier_quantity=None,
            price_list=1,
        )
    )
    session.add(
        ProductPromotion(
            sku="FILT-001",
            price=40,
            discount_percent=52.94,
            valid_from=date.today() - timedelta(days=1),
            valid_to=date.today() + timedelta(days=10),
            tier_quantity=3,
            price_list=1,
        )
    )
    await session.commit()

    rows = await catalog.search_items(
        session,
        None,
        category="Filtros",
        brand="WIX",
        max_price=100,
        only_discount=True,
    )
    assert rows
    assert rows[0].sku == "FILT-001"

    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_show_catalog(category="Filtros")
    assert result["native"] is False
    assert result["products"]
    assert any(
        product.get("promo_price") for product in result["products"]
    )
    assert any(
        product.get("quantity_tiers") for product in result["products"]
    )

    monkeypatch.setattr(settings, "wa_native_catalog_enabled", True)
    monkeypatch.setattr(settings, "wa_catalog_id", "cat-1")
    monkeypatch.setattr(settings, "wa_access_token", "token")
    monkeypatch.setattr(settings, "wa_phone_number_id", "phone")
    result = await toolbox.tool_show_catalog(category="Filtros")
    assert result["native"] is True
    assert toolbox.last_catalog is not None
    assert toolbox.last_catalog["kind"] in {"product", "product_list"}
    assert toolbox.last_catalog["sections"]
