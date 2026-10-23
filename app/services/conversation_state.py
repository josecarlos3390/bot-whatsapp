"""Estado estructurado de la conversación: rubro, marca, medida y presupuesto."""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ConversationState


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value[:80] if value else None


def _size(value: str | None) -> str | None:
    match = re.search(r"\b(\d{2,3})\b", value or "")
    return match.group(1) if match else _clean(value)


async def get_state(
    session: AsyncSession, conversation_id: str
) -> ConversationState:
    row = await session.scalar(
        select(ConversationState).where(
            ConversationState.conversation_id == conversation_id
        )
    )
    if row is None:
        row = ConversationState(conversation_id=conversation_id)
        session.add(row)
        await session.flush()
    return row


async def update_state(
    session: AsyncSession,
    conversation_id: str,
    *,
    category: str | None = None,
    brand: str | None = None,
    size: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    intent: str | None = None,
    last_sku: str | None = None,
) -> ConversationState:
    """Mezcla slots; cambiar de rubro limpia marca y medida anteriores."""
    row = await get_state(session, conversation_id)

    new_category = _clean(category)
    if new_category:
        if row.category and row.category.lower() != new_category.lower():
            row.brand = None
            row.size = None
        row.category = new_category

    if brand is not None:
        row.brand = _clean(brand)
    if size is not None:
        row.size = _size(size)
    if min_price is not None:
        row.min_price = min_price
    if max_price is not None:
        row.max_price = max_price
    if intent is not None:
        row.intent = _clean(intent)
    if last_sku is not None:
        row.last_sku = ((_clean(last_sku) or "")[:64]) or None

    await session.commit()
    return row


def state_text(row: ConversationState | None) -> str:
    if row is None:
        return ""
    parts = []
    if row.category:
        parts.append(f"rubro={row.category}")
    if row.brand:
        parts.append(f"marca={row.brand}")
    if row.size:
        parts.append(f"medida={row.size}")
    if row.max_price is not None:
        parts.append(f"presupuesto_max={row.max_price}")
    if row.last_sku:
        parts.append(f"ultimo_sku={row.last_sku}")
    return "; ".join(parts)
