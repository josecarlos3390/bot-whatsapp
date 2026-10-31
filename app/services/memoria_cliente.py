"""Volver a la charla: el bot recuerda qué estaba viendo el cliente.

Un vendedor que atendió a alguien la semana pasada saluda con memoria:
«la última vez viste el sofá Acapulco, ¿lo retomamos?». Eso es lo que hace
este módulo, con lo que ya está en la base.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from ..models import Contact, Conversation, Message
from . import catalog

logger = logging.getLogger(__name__)

# Pasado este tiempo, recordar el producto resulta raro.
DIAS = 14


async def ultimo_visto(session, contact: Contact) -> dict | None:
    """Último producto que el cliente abrió, si fue hace pocos días."""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return None
    fila = await session.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "in",
            Message.text.like("product:%"),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if fila is None:
        return None
    from datetime import datetime, timedelta, timezone

    creado = fila.created_at
    if creado is not None:
        if creado.tzinfo is None:
            creado = creado.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - creado > timedelta(days=DIAS):
            return None
    sku = (fila.text or "").split(":", 1)[1].strip()
    if not sku:
        return None
    producto = await catalog.get_item(session, sku)
    if producto is None:
        return None
    return {
        "sku": producto.sku,
        "name": (producto.name or "").strip(),
        "price": str(
            getattr(producto, "promo_price", None) or producto.price or ""
        ),
    }


async def saludo_con_memoria(
    agent, session, contact: Contact
) -> tuple[str, str] | None:
    """Frase de bienvenida que retoma lo último que vio: (texto, sku)."""
    try:
        visto = await ultimo_visto(session, contact)
    except Exception:  # noqa: BLE001 - la memoria no frena el saludo
        logger.debug("No se pudo leer el último producto", exc_info=True)
        return None
    if visto is None or not visto["name"]:
        return None
    agent._trace(f"Saludo con memoria: {visto['sku']}")
    nombre = visto["name"][:52]
    precio = _formato(visto["price"])
    detalle = f"*{nombre}*" + (f" (Bs {precio})" if precio else "")
    return (
        f"La última vez viste {detalle}. "
        "¿Seguimos con eso o buscás otra cosa?",
        visto["sku"],
    )


def _formato(valor: str) -> str:
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return ""
    if numero <= 0:
        return ""
    return f"{numero:,.0f}".replace(",", ".")
