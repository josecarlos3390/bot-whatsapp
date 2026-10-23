"""Seguimiento de pedidos VTEX por el ID que llega al correo."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, ConversationFlow
from ..sap import SapError, SapNotFound, get_sap


ORDER_ID_RE = re.compile(r"\b(\d{4,20}(?:-\d{2})?)\b")
STATUS_LABELS = {
    "payment-pending": "Pendiente de pago",
    "waiting-for-authorization": "Esperando autorización",
    "authorized": "Pago autorizado",
    "ready-for-handling": "Listo para preparar",
    "handling": "En preparación",
    "invoiced": "Facturado",
    "shipped": "Enviado",
    "delivered": "Entregado",
    "canceled": "Cancelado",
    "cancelled": "Cancelado",
}


def _conversation(session: AsyncSession, contact: Contact) -> None:
    return None


async def _get_conversation(
    session: AsyncSession, contact: Contact
) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )


async def get_active(
    session: AsyncSession, contact: Contact
) -> ConversationFlow | None:
    conversation = await _get_conversation(session, contact)
    if conversation is None:
        return None
    return await session.scalar(
        select(ConversationFlow).where(
            ConversationFlow.conversation_id == conversation.id,
            ConversationFlow.flow == "order_tracking",
            ConversationFlow.status == "active",
        )
    )


async def start(session: AsyncSession, contact: Contact) -> str:
    conversation = await _get_conversation(session, contact)
    if conversation is None:
        conversation = Conversation(contact_id=contact.id)
        session.add(conversation)
        await session.flush()
    flow = await session.scalar(
        select(ConversationFlow).where(
            ConversationFlow.conversation_id == conversation.id
        )
    )
    if flow is None:
        flow = ConversationFlow(conversation_id=conversation.id)
        session.add(flow)
    flow.flow = "order_tracking"
    flow.step = 0
    flow.answers = {}
    flow.status = "active"
    await session.commit()
    return (
        "Para consultar el seguimiento, pasame el *ID del pedido* que te "
        "llegó por correo. Tiene un formato similar a "
        "*1670220500193-01*.\n\n"
        "Si no lo encontrás, escribí *asesor* y lo revisamos."
    )


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search((text or "").replace(" ", ""))
    if not match:
        return None
    return match.group(1)


def _money(value) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "0")


def _date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value[:16].replace("T", " ")


def _shipping(order: dict) -> tuple[str, str, str]:
    shipping = order.get("shippingData") or {}
    logistics = shipping.get("logisticsInfo") or []
    first = logistics[0] if logistics else {}
    company = first.get("deliveryCompany") or first.get("selectedSla") or ""
    estimate = (
        first.get("shippingEstimateDate")
        or (first.get("deliveryWindow") or {}).get("endDate")
        or ""
    )
    address = shipping.get("address") or {}
    pickup = address.get("addressType") == "pickup"
    place = ""
    if pickup:
        place = f"Retiro: {company or address.get('street') or 'tienda'}"
    else:
        place = f"Entrega: {company or 'domicilio'}"
    if estimate:
        place += f" · estimado {_date(estimate)}"
    tracking = ""
    packages = (order.get("packageAttachment") or {}).get("packages") or []
    for package in packages:
        number = package.get("trackingNumber") or package.get("invoiceNumber")
        url = package.get("trackingUrl")
        courier = package.get("courier")
        parts = []
        if number:
            parts.append(f"guía {number}")
        if courier:
            parts.append(str(courier))
        if url:
            parts.append(str(url))
        if parts:
            tracking = " · ".join(parts)
            break
    return place, tracking, first.get("selectedSla") or ""


def format_order(order: dict) -> str:
    order_id = str(order.get("orderId") or "")
    status = str(order.get("status") or "")
    label = STATUS_LABELS.get(status, order.get("statusDescription") or status)
    lines = [
        f"Pedido *{order_id}*",
        f"Estado: *{label}*",
        f"Total: Bs {_money(order.get('value'))}",
    ]
    items = order.get("items") or []
    if items:
        lines.append("Productos:")
        for item in items[:6]:
            name = item.get("name") or item.get("skuName") or "Producto"
            quantity = item.get("quantity") or 1
            lines.append(f"• {quantity} × {name}")
        if len(items) > 6:
            lines.append(f"• y {len(items) - 6} más")
    place, tracking, _ = _shipping(order)
    if place:
        lines.append(place)
    if tracking:
        lines.append(f"Guía: {tracking}")
    else:
        lines.append("Guía: todavía no hay número de despacho.")
    if status in {"canceled", "cancelled"}:
        lines.append("Este pedido figura como cancelado.")
    return "\n".join(lines)


async def lookup(
    session: AsyncSession, flow: ConversationFlow, text: str
) -> dict:
    order_id = extract_order_id(text)
    answers = dict(flow.answers or {})
    if not order_id:
        answers["attempts"] = int(answers.get("attempts") or 0) + 1
        flow.answers = answers
        await session.commit()
        return {
            "text": (
                "No reconocí un ID de pedido. Pegá el número completo del "
                "correo, por ejemplo *1670220500193-01*."
            ),
            "finished": False,
            "needs_handoff": False,
        }

    try:
        sap = get_sap(session)
        order = None
        # El correo de VTEX a veces muestra el número de secuencia (500193)
        # en lugar del orderId completo. Buscamos en los pedidos recientes.
        if "-" not in order_id and len(order_id) <= 9:
            page = await sap.get_orders_page(page=1, per_page=100)
            for candidate in page.get("list") or []:
                if str(candidate.get("sequence") or "") == order_id:
                    full_id = candidate.get("orderId")
                    if full_id:
                        order = await sap.get_order(str(full_id))
                        order_id = str(full_id)
                    break
        if order is None:
            order = await sap.get_order(order_id)
        if not order:
            raise SapNotFound(order_id)
    except SapNotFound:
        answers["attempts"] = int(answers.get("attempts") or 0) + 1
        flow.answers = answers
        attempts = answers["attempts"]
        await session.commit()
        if attempts >= 3:
            flow.status = "completed"
            await session.commit()
            return {
                "text": (
                    "No encontré ese ID después de varios intentos. "
                    "Te derivo con un asesor para revisarlo."
                ),
                "finished": True,
                "needs_handoff": True,
            }
        return {
            "text": (
                "No encontré ese ID. Revisá el correo de VTEX: el ID tiene "
                "un formato como *1670220500193-01*.\n\n"
                "Probá de nuevo o escribí *asesor*."
            ),
            "finished": False,
            "needs_handoff": False,
        }
    except SapError:
        flow.status = "completed"
        await session.commit()
        return {
            "text": (
                "No pude consultar el pedido en este momento. "
                "Te derivo con un asesor."
            ),
            "finished": True,
            "needs_handoff": True,
        }

    flow.status = "completed"
    flow.answers = {**answers, "order_id": order_id}
    await session.commit()
    return {
        "text": format_order(order),
        "finished": True,
        "needs_handoff": False,
        "order_id": order_id,
    }
