from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models import (
    Cart,
    Contact,
    Order,
    OrderItem,
    Payment,
    utcnow,
)
from ..payments import create_payment
from ..sap import SapAdapter
from . import catalog, cart as cart_service, feedback, pricing

logger = logging.getLogger(__name__)


class CheckoutError(ValueError):
    pass


def payment_url(payment: Payment) -> str:
    return f"{settings.public_base_url.rstrip('/')}/mock/pay/{payment.id}"


async def create_order(
    session: AsyncSession,
    contact: Contact,
    cart: Cart,
    sap: SapAdapter,
) -> tuple[Order, Payment]:
    if cart.status != "active":
        raise CheckoutError("Este carrito ya fue procesado. Inicia uno nuevo.")
    cart_lines = await cart_service.items(session, cart)
    if not cart_lines:
        raise CheckoutError("El carrito está vacío.")

    subtotal = Decimal("0")
    lines: list[OrderItem] = []
    for line in cart_lines:
        offer = await pricing.get_offer(
            session,
            line.sku,
            line.quantity,
            force_refresh=True,
            sap=sap,
        )
        if offer is None:
            raise CheckoutError(f"El producto {line.sku} ya no está disponible.")

        store = line.store_code or cart_service._choose_store(
            offer, line.quantity
        )
        if (
            store is None
            or offer.stock_by_store.get(store, 0) < line.quantity
        ):
            store = cart_service._choose_store(offer, line.quantity)
        if store is None or offer.stock_by_store.get(store, 0) < line.quantity:
            raise CheckoutError(cart_service._stock_error(offer, line.quantity))

        unit_price = Decimal(offer.final_price)
        line_total = unit_price * line.quantity
        subtotal += line_total
        lines.append(
            OrderItem(
                sku=offer.sku,
                name=offer.name,
                quantity=line.quantity,
                unit_price=unit_price,
                list_price=Decimal(offer.base_price),
                discount_percent=Decimal(offer.discount_percent),
                store_code=store,
                line_total=line_total,
            )
        )

    order = Order(
        number=f"WA-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        contact_id=contact.id,
        cart_id=cart.id,
        status="pending_payment",
        subtotal=subtotal,
        total=subtotal,
        currency=cart.currency,
        items=lines,
    )
    session.add(order)
    await session.flush()

    try:
        sap_order = await sap.create_sales_order(order)
        order.sap_doc_entry = sap_order.doc_entry
        order.sap_doc_num = sap_order.doc_num
        # SAP es la fuente de verdad del total (impuestos, redondeos, descuentos).
        order.total = Decimal(sap_order.total)

        payment = await create_payment(session, order)
        cart.status = "checked_out"
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info(
        "Pedido %s creado (SAP DocEntry=%s) por %s %s",
        order.number,
        order.sap_doc_entry,
        order.total,
        order.currency,
    )
    return order, payment


async def confirm_payment(
    session: AsyncSession,
    payment_id: str,
    sap: SapAdapter,
    whatsapp: Any | None = None,
) -> Payment:
    payment = await session.get(Payment, payment_id, with_for_update=True)
    if payment is None:
        raise CheckoutError("Pago no encontrado.")
    if payment.status == "paid":
        return payment  # idempotente: el webhook puede reintentar

    order = await session.scalar(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == payment.order_id)
    )
    if order is None:
        raise CheckoutError("Pedido no encontrado.")

    payment.status = "paid"
    payment.paid_at = utcnow()
    order.status = "paid"
    order.paid_at = payment.paid_at

    invoice = None
    sap_payment = None
    invoice_error: str | None = None
    try:
        invoice = await sap.create_invoice_from_order(order)
        sap_payment = await sap.create_incoming_payment(order, invoice)
    except Exception as exc:  # noqa: BLE001 - el cobro ya se realizó
        # No se revierte el pago: se registra como pagado y la factura queda
        # pendiente (SAP puede rechazarla por permisos, o el integrador puede
        # no exponer todavía el endpoint).
        invoice_error = str(exc)[:300]
        logger.error(
            "Pago %s confirmado sin factura SAP: %s", payment.id, invoice_error
        )

    if invoice is not None:
        order.status = "invoiced"
        order.invoice_doc_entry = invoice.doc_entry
        order.invoice_doc_num = invoice.doc_num
        order.sap_payment_doc_entry = (
            sap_payment.doc_entry if sap_payment else None
        )
        payment.invoice_doc_entry = invoice.doc_entry
        payment.raw = {
            "invoice_doc_entry": invoice.doc_entry,
            "invoice_doc_num": invoice.doc_num,
            "payment_doc_entry": sap_payment.doc_entry if sap_payment else None,
        }
    else:
        order.notes = (
            f"{order.notes}\n" if order.notes else ""
        ) + f"Factura SAP pendiente: {invoice_error}"

    await feedback.create_feedback_request(session, order)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    if whatsapp is not None:
        contact = await session.get(Contact, order.contact_id)
        if contact is not None:
            try:
                if invoice is not None:
                    text = (
                        f"✅ Pago confirmado por {order.total} {order.currency}.\n"
                        f"Pedido {order.number} · Factura SAP {invoice.doc_num}.\n"
                        "Te avisamos cuando salga a despacho."
                    )
                else:
                    text = (
                        f"✅ Pago confirmado por {order.total} {order.currency}.\n"
                        f"Pedido {order.number}. Estamos generando la factura "
                        "y te avisamos cuando salga a despacho."
                    )
                await whatsapp.send_text(contact.wa_id, text)
            except Exception:  # no romper el cobro por un fallo de mensajería
                logger.exception("No se pudo notificar el pago %s", payment.id)

    logger.info(
        "Pago %s confirmado; factura SAP %s; pago SAP %s",
        payment.id,
        invoice.doc_entry if invoice else "pendiente",
        sap_payment.doc_entry if sap_payment else "pendiente",
    )
    return payment


async def latest_order(session: AsyncSession, contact_id: str) -> Order | None:
    return await session.scalar(
        select(Order)
        .where(Order.contact_id == contact_id)
        .order_by(Order.created_at.desc())
        .limit(1)
    )


def order_status_text(order: Order) -> str:
    labels = {
        "pending_payment": "pendiente de pago",
        "paid": "pagado",
        "invoiced": "facturado",
        "cancelled": "cancelado",
    }
    status = labels.get(order.status, order.status)
    invoice = (
        f" · factura SAP {order.invoice_doc_num}"
        if order.invoice_doc_num
        else ""
    )
    return (
        f"Pedido {order.number}: {status} por {order.total} {order.currency}"
        f"{invoice}."
    )


async def expire_stale_payments(session: AsyncSession) -> int:
    """Marca como expirados los pagos vencidos (job programado)."""
    now = datetime.now(timezone.utc)
    rows = (
        await session.scalars(
            select(Payment).where(
                Payment.status == "pending", Payment.expires_at < now
            )
        )
    ).all()
    for payment in rows:
        payment.status = "expired"
    if rows:
        await session.commit()
    return len(rows)
