"""Control de calidad: busca conversaciones donde algo salió mal.

No mira todo: detecta patrones concretos sobre conversaciones reales.

- producto ofrecido ante un tema delicado (duelo, salud…),
- venta a un cliente enojado,
- producto que nadie pidió,
- frases prohibidas que llegaron al cliente,
- mensajes que quedaron sin respuesta.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message
from . import intent, output_guard

logger = logging.getLogger(__name__)

PRODUCT_MARKERS = (
    "precio:",
    "precio de lista",
    "decime cuál te interesa",
    "sku:",
    "agregar 1",
)


def _is_product_message(type_: str | None, text: str | None) -> bool:
    if (type_ or "") in ("image", "product", "catalog"):
        return True
    lowered = (text or "").lower()
    return any(marker in lowered for marker in PRODUCT_MARKERS)


def _has_banned(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in output_guard.BANNED_PHRASES)


async def scan(
    session: AsyncSession, hours: int = 72, limit: int = 600
) -> dict:
    """Devuelve los casos sospechosos de las últimas horas."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(hours=max(int(hours), 1))
    rows = (
        await session.execute(
            select(
                Message.conversation_id,
                Message.direction,
                Message.text,
                Message.type,
                Message.created_at,
            )
            .where(Message.created_at >= since)
            .order_by(Message.conversation_id, Message.created_at)
            .limit(limit * 4)
        )
    ).all()

    issues: list[dict] = []
    pending: dict[str, dict] = {}

    def add(kind: str, inbound: str, outbound: str | None, at) -> None:
        issues.append(
            {
                "kind": kind,
                "inbound": (inbound or "")[:180],
                "outbound": (outbound or "")[:180],
                "at": at.isoformat() if at else None,
            }
        )

    for conversation_id, direction, text, type_, created_at in rows:
        if direction == "in":
            pending[conversation_id] = {
                "text": text,
                "at": created_at,
            }
            continue

        inbound = pending.pop(conversation_id, None)
        if inbound is None:
            continue

        decision = intent.rules(inbound["text"])
        offers_product = _is_product_message(type_, text)

        if decision.get("sensitive") and offers_product:
            add("tema_delicitado", inbound["text"], text, created_at)
        elif decision.get("frustrated") and offers_product:
            add("enojo_con_venta", inbound["text"], text, created_at)
        elif offers_product and not decision.get("buy"):
            if "catalog" not in (inbound["text"] or "").lower():
                add("producto_sin_pedido", inbound["text"], text, created_at)

        if _has_banned(text):
            add("frase_prohibida", inbound["text"], text, created_at)

    # Mensajes del cliente que quedaron sin respuesta.
    for conversation_id, item in pending.items():
        at = item["at"]
        if at is not None and isinstance(at, datetime):
            naive = at.replace(tzinfo=None) if at.tzinfo else at
            if now - naive > timedelta(minutes=10):
                add("sin_respuesta", item["text"], None, at)

    order = {
        "tema_delicitado": 0,
        "enojo_con_venta": 1,
        "producto_sin_pedido": 2,
        "frase_prohibida": 3,
        "sin_respuesta": 4,
    }
    issues.sort(key=lambda issue: order.get(issue["kind"], 9))
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["kind"]] = counts.get(issue["kind"], 0) + 1

    return {
        "hours": int(hours),
        "total": len(issues),
        "counts": counts,
        "issues": issues[:20],
    }
