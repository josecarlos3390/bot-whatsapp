from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Cart, Contact, Order
from app.sap import MockSap
from app.services import cart as cart_service
from app.services.orders import confirm_payment, create_order


class FakeWhatsApp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> str:
        self.sent.append((to, text))
        return "wamid.fake"


async def _contact(session) -> Contact:
    contact = Contact(wa_id="59179462889", phone_e164="+59179462889", name="Ana")
    session.add(contact)
    await session.commit()
    return contact


async def test_add_to_cart_and_totals(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)

    await cart_service.add_item(session, cart, "FILT-001", 2)
    summary = await cart_service.summary(session, cart)

    assert summary["count"] == 2
    assert summary["total"] == Decimal("170.00")
    assert summary["items"][0]["name"].startswith("Filtro de aceite")


async def test_quantity_update_remove_and_clear(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 2)

    await cart_service.set_quantity(session, cart, "FILT-001", 1)
    summary = await cart_service.summary(session, cart)
    assert summary["count"] == 1

    await cart_service.remove_item(session, cart, "FILT-001")
    assert await cart_service.summary(session, cart) == {
        "items": [],
        "count": 0,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
        "currency": "BOB",
    }

    await cart_service.add_item(session, cart, "FILT-002", 1)
    await cart_service.clear(session, cart)
    assert (await cart_service.summary(session, cart))["items"] == []


async def test_stock_limit_is_enforced(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)

    try:
        await cart_service.add_item(session, cart, "BATE-002", 99)
    except cart_service.CartError as exc:
        assert "Disponible por tienda" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Se esperaba CartError")


async def test_checkout_and_payment_creates_invoice_and_sap_payment(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 2)

    order, payment = await create_order(session, contact, cart, MockSap(session))

    assert order.status == "pending_payment"
    assert order.total == Decimal("170.00")
    assert order.sap_doc_entry is not None
    assert payment.status == "pending"
    assert payment.qr_payload and "order" in payment.qr_payload
    assert cart.status == "checked_out"

    fake = FakeWhatsApp()
    await confirm_payment(session, payment.id, MockSap(session), fake)
    await session.refresh(order)
    await session.refresh(payment)

    assert payment.status == "paid"
    assert order.status == "invoiced"
    assert order.invoice_doc_entry is not None
    assert order.sap_payment_doc_entry is not None
    assert payment.invoice_doc_entry == order.invoice_doc_entry
    assert fake.sent and "Pago confirmado" in fake.sent[0][1]


async def test_payment_confirmation_is_idempotent(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "ACEI-001", 1)
    order, payment = await create_order(session, contact, cart, MockSap(session))

    await confirm_payment(session, payment.id, MockSap(session))
    first_invoice = order.invoice_doc_entry

    await confirm_payment(session, payment.id, MockSap(session))
    assert order.invoice_doc_entry == first_invoice


class FailingSap(MockSap):
    async def create_sales_order(self, order):  # type: ignore[override]
        raise RuntimeError("SAP no disponible")


async def test_checkout_rolls_back_if_sap_fails(session):
    contact = await _contact(session)
    cart = await cart_service.get_or_create_cart(session, contact.id)
    cart_id = cart.id
    await cart_service.add_item(session, cart, "FILT-001", 1)

    with pytest.raises(RuntimeError):
        await create_order(session, contact, cart, FailingSap(session))

    orders = await session.scalar(select(func.count()).select_from(Order))
    assert orders == 0
    fresh_cart = await session.get(Cart, cart_id)
    assert fresh_cart is not None and fresh_cart.status == "active"
