"""Carrito sin terminar: recordarle al cliente lo que dejó.

Dos caminos según la ventana de WhatsApp:

- Si el cliente escribió en las últimas 24 h, se manda un **mensaje libre**
  (con los datos del carrito que están en la base).
- Si pasó más tiempo, solo se puede iniciar con una **plantilla aprobada**;
  el texto de la plantilla es fijo y los datos van como variables.

En ambos casos el contenido sale de la base: productos, cantidades y total.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from ..config import settings
from ..models import (
    Cart,
    CartItem,
    CartReminder,
    Contact,
    Conversation,
    Message,
)
logger = logging.getLogger(__name__)

VENTANA_HORAS = 24


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _consiente(momento: datetime | None) -> datetime:
    if momento is None:
        return _ahora()
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _total(items: list[CartItem]) -> Decimal:
    return sum(
        (Decimal(item.unit_price or 0) * int(item.quantity or 0) for item in items),
        Decimal("0"),
    )


def _formato(valor: Decimal | float) -> str:
    return f"{Decimal(valor):,.0f}".replace(",", ".")


async def ventana_abierta(session, contact: Contact) -> bool:
    """¿El cliente escribió en las últimas 24 horas?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    ultimo = await session.scalar(
        select(Message.created_at)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "in",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if ultimo is None:
        return False
    return _ahora() - _consiente(ultimo) < timedelta(hours=VENTANA_HORAS)


async def pendientes(
    session, horas: int = 3, limite: int = 50
) -> list[tuple[Cart, Contact, list[CartItem]]]:
    """Carritos con ítems, quietos hace un rato y sin recordatorio enviado."""
    corte = _ahora() - timedelta(hours=max(horas, 1))
    hace_una_semana = _ahora() - timedelta(days=7)
    carritos = (
        await session.scalars(
            select(Cart)
            .where(
                Cart.status == "active",
                Cart.updated_at <= corte,
            )
            .order_by(Cart.updated_at.desc())
            .limit(limite * 3)
        )
    ).all()

    salida = []
    for carrito in carritos:
        items = (
            await session.scalars(
                select(CartItem).where(CartItem.cart_id == carrito.id)
            )
        ).all()
        if not items:
            continue
        reciente = await session.scalar(
            select(CartReminder.id)
            .where(
                CartReminder.cart_id == carrito.id,
                CartReminder.sent_at >= hace_una_semana,
            )
            .limit(1)
        )
        if reciente is not None:
            continue
        contacto = await session.get(Contact, carrito.contact_id)
        if contacto is None:
            continue
        conversacion = await session.scalar(
            select(Conversation).where(
                Conversation.contact_id == contacto.id
            )
        )
        if conversacion is not None and conversacion.bot_paused:
            continue  # con un asesor: no se manda publicidad
        salida.append((carrito, contacto, list(items)))
        if len(salida) >= limite:
            break
    return salida


async def enriquecer(session, items: list[CartItem]) -> list[dict]:
    """Nombre y precio de cada ítem, para el mensaje."""
    from . import catalog

    salida = []
    for item in items:
        articulo = await catalog.get_item(session, item.sku)
        salida.append(
            {
                "sku": item.sku,
                "name": (articulo.name if articulo else item.sku),
                "quantity": int(item.quantity or 0),
                "unit_price": Decimal(item.unit_price or 0),
            }
        )
    return salida


def _nombre_pila(contacto: Contact) -> str:
    """Primer nombre, solo si es un nombre de verdad."""
    import re

    crudo = (contacto.name or "").strip()
    primero = crudo.split(" ")[0] if crudo else ""
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", primero):
        return ""
    return primero[:24]


def texto_con_nombres(
    contacto: Contact,
    filas: list[dict],
    total: Decimal,
    enlace: str = "",
) -> str:
    nombre = _nombre_pila(contacto)
    saludo = f"Hola {nombre}" if nombre else "Hola"
    lineas = [f"{saludo} 👋 quedó esto en tu carrito:"]
    for fila in filas[:5]:
        importe = fila["unit_price"] * fila["quantity"]
        lineas.append(
            f"• {fila['quantity']} × {fila['name'][:48]} — Bs {_formato(importe)}"
        )
    if len(filas) > 5:
        lineas.append(f"• y {len(filas) - 5} más")
    lineas.append(f"\nTotal: *Bs {_formato(total)}*")
    if enlace:
        lineas.append(f"\nTerminá la compra acá: {enlace}")
    lineas.append("\n¿Querés que lo terminemos? Decime *retomar carrito*.")
    return "\n".join(lineas)


async def recordar(session, carrito: Cart, contacto: Contact, items) -> dict:
    """Manda el recordatorio y lo deja registrado.

    Devuelve el resultado con el canal usado o el motivo por el que no se
    pudo enviar.
    """
    from ..runtime import whatsapp

    filas = await enriquecer(session, items)
    total = sum(
        (fila["unit_price"] * fila["quantity"] for fila in filas),
        Decimal("0"),
    )
    # Si el carrito está en VTEX: se confirma que sigue vigente antes de
    # mandar el link (y el total pasa a ser el de VTEX).
    enlace = ""
    from . import vtex_cart

    if vtex_cart.disponible() and carrito.vtex_order_form_id:
        if await vtex_cart.asegurar_vigente(carrito):
            enlace = vtex_cart.link_para_pagar(carrito)
            if carrito.vtex_value:
                total = Decimal(carrito.vtex_value)
        else:
            carrito.vtex_order_form_id = ""
            carrito.vtex_cart_url = ""
            await session.commit()
    abierta = await ventana_abierta(session, contacto)
    canal = "text"
    if abierta:
        await whatsapp.send_text(
            contacto.wa_id,
            texto_con_nombres(contacto, filas, total, enlace=enlace),
        )
    elif settings.cart_template_name:
        canal = "template"
        await whatsapp.send_template(
            contacto.wa_id,
            settings.cart_template_name,
            language=settings.cart_template_lang,
            parameters=[
                _nombre_pila(contacto) or "cliente",
                str(len(filas)),
                filas[0]["name"][:60] if filas else "tus productos",
                _formato(total),
            ],
        )
    else:
        return {"ok": False, "motivo": "ventana cerrada y sin plantilla"}

    session.add(
        CartReminder(
            cart_id=carrito.id,
            contact_id=contacto.id,
            channel=canal,
            sent_at=_ahora(),
        )
    )
    await session.commit()
    logger.info("Recordatorio de carrito enviado a %s (%s)", contacto.wa_id, canal)
    return {"ok": True, "canal": canal, "items": len(filas), "total": float(total)}
