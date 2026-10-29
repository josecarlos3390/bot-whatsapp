"""Seguimiento de pedidos VTEX por el ID que llega al correo."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, Conversation, ConversationFlow
from ..sap import SapError, SapNotFound, get_sap


# El ID se busca dentro del texto tal cual: quitar los espacios pegaba el
# número a la palabra anterior y el borde de palabra no coincidía
# ("mipedido1234-01" no tenía límite antes de los dígitos).
ORDER_ID_RE = re.compile(r"(?<!\d)(\d{4,20}(?:-\d{1,3})?)(?!\d)")
# Código de estado de VTEX -> (etiqueta, qué significa, siguiente paso).
# VTEX devuelve el código en inglés y una descripción en portugués
# ("Pronto para o manuseio"); acá se traduce y se explica qué hacer.
STATUS_GUIDE = {
    "on-order-completed": (
        "Pedido creado",
        "El pedido se registró pero todavía no se pagó.",
        "Completá el pago para que avance.",
    ),
    "payment-pending": (
        "Pendiente de pago",
        "Estamos esperando la confirmación del pago.",
        "Si ya pagaste, puede tardar unos minutos en acreditarse.",
    ),
    "payment-approved": (
        "Pago aprobado",
        "El pago se acreditó y el pedido entra en preparación.",
        "No tenés que hacer nada más.",
    ),
    "authorized": (
        "Pago autorizado",
        "El pago quedó autorizado por el banco.",
        "No tenés que hacer nada más.",
    ),
    "waiting-for-authorization": (
        "Esperando autorización",
        "El banco todavía no confirmó el pago.",
        "Si demora, consultá con tu banco o pedí un asesor.",
    ),
    "ready-for-handling": (
        "Listo para preparar",
        "El pago está confirmado y el pedido espera ser armado.",
        "Te avisamos cuando salga para entrega.",
    ),
    "handling": (
        "En preparación",
        "Estamos armando y embalando tu pedido.",
        "Te avisamos cuando salga para entrega.",
    ),
    "invoiced": (
        "Facturado",
        "El pedido se facturó y está listo para despacho.",
        "En breve sale para entrega.",
    ),
    "shipped": (
        "En camino",
        "El pedido salió del depósito.",
        "Te contactamos para coordinar la entrega.",
    ),
    "delivered": (
        "Entregado",
        "El pedido figura como entregado.",
        "Si no lo recibiste, avisanos y lo revisamos.",
    ),
    "canceled": (
        "Cancelado",
        "El pedido fue cancelado.",
        "Si no lo cancelaste vos, pedí un asesor.",
    ),
    "cancelled": (
        "Cancelado",
        "El pedido fue cancelado.",
        "Si no lo cancelaste vos, pedí un asesor.",
    ),
    "request-cancel": (
        "Cancelación solicitada",
        "Pediste cancelar y está en revisión.",
        "Te confirmamos cuando se procese.",
    ),
}

STATUS_LABELS = {codigo: datos[0] for codigo, datos in STATUS_GUIDE.items()}


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
    from .order_by_document import lookup_by_document, lookup_by_phone

    # Primero se intenta con el teléfono de la conversación: si el sistema
    # resuelve, el cliente no tiene que escribir nada.
    encontrado = None
    if settings.order_phone_lookup_enabled:
        try:
            encontrado = await lookup_by_phone(session, contact)
        except Exception:  # noqa: BLE001 - el intento no debe romper el flujo
            encontrado = None
    if encontrado and encontrado.get("text"):
        return encontrado["text"]

    # Si el cliente ya se identificó antes, el documento quedó guardado:
    # la consulta se resuelve sola, sin volver a pedirlo.
    if contact.tax_id:
        try:
            guardado = await lookup_by_document(
                session, contact, contact.tax_id, "carnet"
            )
        except Exception:  # noqa: BLE001 - se sigue con el pedido normal
            guardado = None
        if guardado and guardado.get("text") and not guardado.get(
            "needs_handoff"
        ):
            return guardado["text"]

    return (
        "Para consultar el seguimiento pasame el *ID del pedido* "
        "(por ejemplo *1670220500193-01*).\n\n"
        "Si no lo tenés a mano, pasame tu *CI o NIT* y busco tus compras a "
        "tu nombre. También podés escribir *asesor*."
    )


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search(text or "")
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
    guia = STATUS_GUIDE.get(status)
    if guia:
        lines.append(guia[1])
        lines.append(f"→ {guia[2]}")
    items = order.get("items") or []
    if items:
        lines.append("Productos:")
        for item in items[:6]:
            name = item.get("name") or item.get("skuName") or "Producto"
            quantity = item.get("quantity") or 1
            # Código VTEX del artículo: es lo que figura en la caja y en la
            # factura, y ayuda al cliente a identificar qué le llegó.
            codigo = str(
                item.get("skuCode")
                or item.get("refId")
                or item.get("id")
                or ""
            ).strip()
            sufijo = f" ({codigo})" if codigo and codigo != name else ""
            lines.append(f"• {quantity} × {name}{sufijo}")
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
    from .order_by_document import (
        extract_documento,
        extract_email,
        lookup_by_document,
        pregunta_tipo,
        tipo_del_texto,
    )

    contact = await session.get(Contact, flow.contact_id) if hasattr(flow, "contact_id") else None
    if contact is None:
        conversacion = await session.get(Conversation, flow.conversation_id)
        if conversacion is not None:
            contact = await session.get(Contact, conversacion.contact_id)

    order_id = extract_order_id(text)
    answers = dict(flow.answers or {})

    # Botón de tipo ("doc:carnet", "doc:nit", "doc:telefono").
    if (text or "").strip().lower().startswith("doc:"):
        kind = text.split(":", 1)[1].strip().lower()
        numero = str(answers.get("numero") or "")
        flow.status = "completed"
        await session.commit()
        if not numero:
            return {
                "text": "Pasame el número de nuevo, por favor.",
                "finished": False,
                "needs_handoff": False,
            }
        return await lookup_by_document(session, contact, numero, kind)

    # Si el cliente pasa un email, se busca por esa llave (segunda opción
    # después del documento según la validación de VTEX).
    email = extract_email(text)
    if email:
        flow.status = "completed"
        await session.commit()
        from .order_by_document import lookup_by_email

        return await lookup_by_email(session, contact, email)

    # Si el cliente ofrece su documento (o no recuerda el número), se busca
    # por carnet/NIT/teléfono. Antes el bot insistía con el ID y no avanzaba.
    documento = extract_documento(text)
    es_id_largo = bool(order_id) and (
        "-" in (order_id or "") or len(order_id or "") >= 13
    )
    if documento and not es_id_largo:
        kind = tipo_del_texto(text)
        if kind:
            flow.status = "completed"
            await session.commit()
            return await lookup_by_document(
                session, contact, documento, kind
            )
        # Número sin contexto: se pregunta qué es antes de buscar, para no
        # consultar con el criterio equivocado.
        answers["numero"] = documento
        flow.answers = answers
        await session.commit()
        return pregunta_tipo(documento)
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
