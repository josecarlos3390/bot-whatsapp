"""Escalado de casos que esperan demasiado.

Un caso en cola (o asignado sin tomar) que supera el tiempo de espera se
marca como escalado, se registra en su historial y se avisa al supervisor
por el mismo canal de eventos del panel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Handoff, HandoffEvent

logger = logging.getLogger(__name__)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


async def escalate_stale(session: AsyncSession) -> dict:
    """Marca los casos vencidos y devuelve cuántos escaló."""
    limite = _ahora() - timedelta(minutes=max(settings.handoff_escalate_minutes, 1))
    casos = (
        await session.scalars(
            select(Handoff)
            .where(
                Handoff.status.in_(("queued", "pending")),
                Handoff.escalated_at.is_(None),
                Handoff.created_at <= limite,
            )
            .order_by(Handoff.created_at)
            .limit(50)
        )
    ).all()
    for caso in casos:
        caso.escalated_at = _ahora()
        session.add(
            HandoffEvent(
                handoff_id=caso.id,
                advisor=None,
                action="escalated",
                detail=(
                    "Sin tomar en cola"
                    if caso.status == "queued"
                    else "Asignado sin tomar"
                ),
            )
        )
    if casos:
        await session.commit()
        logger.warning("Casos escalados por demora: %s", len(casos))
    return {"escalated": len(casos)}


async def summary(session: AsyncSession) -> dict:
    """Cuántos casos esperan y cuántos ya están escalados."""
    ahora = _ahora()
    abiertos = (
        await session.scalars(
            select(Handoff).where(Handoff.status.in_(("queued", "pending", "taken")))
        )
    ).all()
    esperando = []
    for caso in abiertos:
        creado = caso.created_at
        if creado is not None and creado.tzinfo is None:
            creado = creado.replace(tzinfo=timezone.utc)
        minutos = int((ahora - creado).total_seconds() // 60) if creado else 0
        esperando.append((caso, minutos))
    por_vencer = [
        c
        for c, minutos in esperando
        if minutos < settings.handoff_escalate_minutes
        and c.status in ("queued", "pending")
    ]
    return {
        "queued": sum(1 for c in abiertos if c.status == "queued"),
        "pending": sum(1 for c in abiertos if c.status == "pending"),
        "escalated": sum(1 for c in abiertos if c.escalated_at is not None),
        "por_vencer": len(por_vencer),
        "oldest_minutes": max((m for _c, m in esperando), default=0),
        "count": int(await session.scalar(select(func.count()).select_from(Handoff)) or 0),
    }
