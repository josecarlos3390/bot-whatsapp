"""Inicio de una charla nueva dentro del mismo chat.

WhatsApp mantiene un único hilo por número, pero una charla de compras no es
la misma después de varias horas. Se conserva el historial (para personalizar),
pero se limpian los datos de trabajo: rubro, marca, medida, pregunta pendiente.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, Conversation
from . import conversation_guard, conversation_state

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _gap_minutes(last: datetime | None) -> int | None:
    if last is None:
        return None
    if last.tzinfo is not None:
        last = last.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0, int((_now() - last).total_seconds() // 60))


async def start_new_if_needed(
    session: AsyncSession,
    conversation: Conversation | None,
    contact: Contact,
) -> dict:
    """Limpia el contexto de trabajo si pasó demasiado tiempo.

    Devuelve ``{"new": bool, "gap_minutes": int | None}``.
    """
    if conversation is None:
        return {"new": False, "gap_minutes": None}

    gap = _gap_minutes(conversation.last_message_at)
    limit = max(1, int(settings.session_gap_minutes))
    if gap is None or gap < limit:
        return {"new": False, "gap_minutes": gap}

    try:
        state = await conversation_state.get_state(session, conversation.id)
        state.category = None
        state.brand = None
        state.size = None
        state.min_price = None
        state.max_price = None
        state.intent = None
        state.last_sku = None
        await session.commit()
        await conversation_guard.clear_pending(session, contact)
        logger.info(
            "Charla nueva tras %s minutos sin hablar (%s)",
            gap,
            contact.wa_id,
        )
    except Exception:  # noqa: BLE001 - no frenar la respuesta
        logger.exception("No se pudo reiniciar el contexto de la charla")

    return {"new": True, "gap_minutes": gap}
