"""Faltantes: qué piden los clientes y no está en el catálogo.

Sirve para compras: muestra los términos que no se encontraron, la intención
que detectó la IA y con qué productos relacionados se respondió.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MissingRequest

logger = logging.getLogger(__name__)


async def record(
    session: AsyncSession,
    term: str,
    intent: str = "",
    related: list[str] | None = None,
    answered: bool = False,
) -> None:
    """Guarda un faltante (sin romper la conversación si falla)."""
    termino = (term or "").strip()[:200]
    if not termino:
        return
    try:
        session.add(
            MissingRequest(
                term=termino,
                intent=(intent or "")[:200] or None,
                related=(
                    json.dumps(related[:8], ensure_ascii=False)
                    if related
                    else None
                ),
                answered=answered,
            )
        )
        await session.commit()
    except Exception:  # noqa: BLE001 - nunca romper por una métrica
        logger.debug("No se pudo registrar el faltante", exc_info=True)
        await session.rollback()


async def resumen(session: AsyncSession, dias: int = 30, limite: int = 20) -> dict:
    """Términos más pedidos que no existen, con su intención."""
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filas = (
        await session.execute(
            select(
                MissingRequest.term,
                func.count(MissingRequest.id),
                func.max(MissingRequest.intent),
                func.max(MissingRequest.created_at),
            )
            .where(MissingRequest.created_at >= desde)
            .group_by(MissingRequest.term)
            .order_by(func.count(MissingRequest.id).desc())
            .limit(limite)
        )
    ).all()
    total = await session.scalar(
        select(func.count(MissingRequest.id)).where(
            MissingRequest.created_at >= desde
        )
    )
    con_respuesta = await session.scalar(
        select(func.count(MissingRequest.id)).where(
            MissingRequest.created_at >= desde,
            MissingRequest.answered.is_(True),
        )
    )
    return {
        "dias": dias,
        "total": int(total or 0),
        "con_respuesta": int(con_respuesta or 0),
        "terminos": [
            {
                "term": termino,
                "veces": veces,
                "intencion": intencion or "",
                "ultima": ultima.isoformat() if ultima else None,
            }
            for termino, veces, intencion, ultima in filas
        ],
    }
