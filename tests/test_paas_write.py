from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.agent import Agent
from app.config import settings
from app.models import CatalogItem, Contact, Order, OrderItem
from app.sap import MockSap, PaasSap, SapError
from app.services import cart as cart_service, catalog
from app.services.orders import confirm_payment, create_order


def _paas_transport(calls: list[dict], *, doc_entry: int = 4321) -> httpx.MockTransport:
    """Transporte falso del integration-paas: lecturas + alta de pedido."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/api/sap/items/"):
            if path.endswith("/pricing"):
                return httpx.Response(200, json={"periods": []})
            sku = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "sku": sku,
                    "name": "PRODUCTO PAAS",
                    "price": 149.0,
                    "stock": 5,
                    "currency": "BOB",
                    "stock_by_store": {"101-1001": 5, "102-1001": 0, "103-1001": 0},
                },
            )
        if request.method == "POST" and path == "/api/sap/business-partners":
            body = json.loads(request.content)
            calls.append({"kind": "bp", "body": body})
            return httpx.Response(200, json={"cardCode": body["cardCode"]})
        if request.method == "POST" and path == "/api/crm/orders":
            body = json.loads(request.content)
            calls.append({"kind": "order", "body": body})
            return httpx.Response(
                200,
                json={"sapDocEntry": doc_entry, "sapDocNum": 99, "status": "created"},
            )
        return httpx.Response(404, json={"error": f"sin ruta {request.method} {path}"})

    return httpx.MockTransport(handler)


def _paas(monkeypatch, calls: list[dict], session) -> PaasSap:
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.test")
    monkeypatch.setattr(settings, "sap_paas_api_key", "test-key")
    monkeypatch.setattr(settings, "sap_write_enabled", True)
    monkeypatch.setattr(settings, "sap_costing_code", "14304")
    monkeypatch.setattr(settings, "sap_costing_code2", "ECO")
    monkeypatch.setattr(settings, "sap_costing_code3", "1000")
    monkeypatch.setattr(settings, "sap_tax_code", "IVA")
    monkeypatch.setattr(settings, "sap_default_card_code", "CF-TEST")
    sap = PaasSap(session)
    sap._client = httpx.AsyncClient(
        base_url="http://paas.test", transport=_paas_transport(calls)
    )
    return sap


async def test_paas_creates_order_with_costing_and_tax(session, monkeypatch):
    calls: list[dict] = []
    sap = _paas(monkeypatch, calls, session)
    contact = Contact(wa_id="59179462889", phone_e164="+59179462889", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 2)

    order, payment = await create_order(session, contact, cart, sap)
    await sap.close()

    assert order.sap_doc_entry == 4321
    payload = next(c for c in calls if c["kind"] == "order")["body"]
    assert payload["crmOrderId"] == order.number
    assert payload["lines"][0]["sku"] == "FILT-001"
    assert payload["lines"][0]["costingCode"] == "14304"
    assert payload["lines"][0]["costingCode2"] == "ECO"
    assert payload["lines"][0]["costingCode3"] == "1000"
    assert payload["lines"][0]["taxCode"] == "IVA"
    assert payment.status == "pending"


async def test_paas_creates_business_partner_when_tax_id_present(session, monkeypatch):
    calls: list[dict] = []
    sap = _paas(monkeypatch, calls, session)
    contact = Contact(
        wa_id="59170000124",
        phone_e164="+59170000124",
        name="Cliente Nuevo",
        tax_id="11111111-1",
    )
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 1)

    order, _ = await create_order(session, contact, cart, sap)
    await sap.close()

    assert order.sap_doc_entry == 4321
    bp = next(c for c in calls if c["kind"] == "bp")["body"]
    assert bp["federalTaxId"] == "11111111-1"
    assert bp["cardCode"] == "WA59170000124"


async def test_paas_uses_default_card_code_without_tax_id(session, monkeypatch):
    calls: list[dict] = []
    sap = _paas(monkeypatch, calls, session)
    monkeypatch.setattr(settings, "sap_default_card_code", "CF-001")
    contact = Contact(wa_id="59170000125", phone_e164="+59170000125", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 1)

    await create_order(session, contact, cart, sap)
    await sap.close()

    payload = next(c for c in calls if c["kind"] == "order")["body"]
    assert payload["customerId"] == "CF-001"


async def test_paas_checkout_requires_identification(session, monkeypatch):
    calls: list[dict] = []
    sap = _paas(monkeypatch, calls, session)
    monkeypatch.setattr(settings, "sap_default_card_code", "")
    contact = Contact(wa_id="59170000126", phone_e164="+59170000126", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 1)

    with pytest.raises(SapError, match="CardCode"):
        await create_order(session, contact, cart, sap)
    await sap.close()


async def test_paas_write_disabled_blocks_order(session, monkeypatch):
    calls: list[dict] = []
    sap = _paas(monkeypatch, calls, session)
    monkeypatch.setattr(settings, "sap_write_enabled", False)
    contact = Contact(wa_id="59170000127", phone_e164="+59170000127", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 1)

    with pytest.raises(SapError, match="SAP_WRITE_ENABLED"):
        await create_order(session, contact, cart, sap)
    await sap.close()


class _InvoiceFails(MockSap):
    async def create_invoice_from_order(self, order):
        raise SapError("El usuario no está autorizado para este almacén")


async def test_payment_confirmed_even_if_invoice_fails(session):
    contact = Contact(wa_id="59179462889", phone_e164="+59179462889", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 2)
    order, payment = await create_order(session, contact, cart, MockSap(session))

    await confirm_payment(session, payment.id, _InvoiceFails(session))

    await session.refresh(payment)
    await session.refresh(order)
    assert payment.status == "paid"
    assert order.status == "paid"
    assert order.invoice_doc_entry is None
    assert "Factura SAP pendiente" in (order.notes or "")


async def test_status_reply_is_deterministic(session):
    contact = Contact(wa_id="59179462889", phone_e164="+59179462889", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    order = Order(
        number="WA-TEST-1",
        contact_id=contact.id,
        cart_id=cart.id,
        status="paid",
        subtotal=Decimal("170"),
        total=Decimal("170"),
        currency="BOB",
        notes="Factura SAP pendiente: sin permisos",
    )
    session.add(order)
    await session.commit()

    reply = await Agent()._status_reply(session, contact)
    text = reply.messages[0].text
    assert "WA-TEST-1" in text
    assert "pagado, factura pendiente" in text


async def test_search_intent_category_does_not_hide_name_matches(session):
    session.add(
        CatalogItem(
            sku="LAMP-1",
            name="LAMPARA MATA MOSQUITO GLEECON",
            category="AIRE LIBRE",
            price=149,
            stock=3,
        )
    )
    await session.commit()

    found = await catalog.search_items(session, "lampara", limit=5)
    assert [item.sku for item in found] == ["LAMP-1"]

    two_words = await catalog.search_items(session, "lampara gleecon", limit=5)
    assert [item.sku for item in two_words] == ["LAMP-1"]
