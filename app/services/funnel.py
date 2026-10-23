"""Embudo de venta: registrar pasos y resumirlos para el panel.

Los pasos son los mismos con carrito propio o con el catálogo/carrito nativo de
WhatsApp: búsqueda → ficha → carrito → checkout → pedido → pago.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, FunnelEvent

logger = logging.getLogger(__name__)

STEPS: tuple[str, ...] = (
    "search",
    "product_view",
    "cart_add",
    "checkout_start",
    "order_created",
    "payment_paid",
)

LABELS: dict[str, str] = {
    "search": "Búsquedas",
    "product_view": "Fichas vistas",
    "cart_add": "Agregados al carrito",
    "checkout_start": "Checkout iniciado",
    "order_created": "Pedidos creados",
    "payment_paid": "Pagos confirmados",
}


async def track(
    session: AsyncSession,
    step: str,
    *,
    contact: Contact | None = None,
    contact_id: str | None = None,
    conversation_id: str | None = None,
    sku: str | None = None,
    query: str | None = None,
    value: Decimal | None = None,
) -> None:
    """Anota un paso. No hace commit: lo hace el flujo que ya está guardando."""
    if step not in STEPS:
        logger.warning("Paso de embudo desconocido: %s", step)
        return
    session.add(
        FunnelEvent(
            step=step,
            contact_id=contact_id or getattr(contact, "id", None),
            conversation_id=conversation_id,
            sku=(sku or "")[:64] or None,
            query=(query or "").strip()[:160] or None,
            value=value,
        )
    )


async def stats(
    session: AsyncSession, days: int = 30
) -> dict:
    """Contactos únicos por paso, conversión y valor de los pedidos."""
    since = datetime.now(timezone.utc) - timedelta(days=max(int(days), 1))

    per_contact = (
        await session.execute(
            select(
                FunnelEvent.step,
                func.count(func.distinct(FunnelEvent.contact_id)),
                func.count(FunnelEvent.id),
            )
            .where(FunnelEvent.created_at >= since)
            .group_by(FunnelEvent.step)
        )
    ).all()
    by_step = {step: (int(contacts), int(events)) for step, contacts, events in per_contact}

    revenue = await session.scalar(
        select(func.coalesce(func.sum(FunnelEvent.value), 0)).where(
            FunnelEvent.step == "payment_paid",
            FunnelEvent.created_at >= since,
        )
    )

    rows: list[dict] = []
    previous: int | None = None
    for step in STEPS:
        contacts, events = by_step.get(step, (0, 0))
        conversion = None
        if previous not in (None, 0):
            conversion = round(contacts * 100.0 / previous, 1)
        rows.append(
            {
                "step": step,
                "label": LABELS[step],
                "contacts": contacts,
                "events": events,
                "conversion": conversion,
            }
        )
        if contacts:
            previous = contacts

    return {
        "days": int(days),
        "steps": rows,
        "revenue": str(Decimal(str(revenue or 0))),
    }


async def track_and_commit(session: AsyncSession, step: str, **kwargs) -> None:
    """Registra un paso y lo confirma de inmediato.

    Para pasos cuyo flujo puede hacer rollback (checkout fallido): el intento
    cuenta igual en el embudo.
    """
    try:
        await track(session, step, **kwargs)
        await session.commit()
    except Exception:  # noqa: BLE001 - la analítica no rompe la venta
        logger.debug("No se pudo guardar el paso %s", step, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Rollback del embudo falló", exc_info=True)
