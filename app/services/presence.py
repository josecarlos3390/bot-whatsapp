"""Presencia de asesores y reparto de casos.

- El panel manda un latido cada 30 s: eso marca al asesor como conectado.
- Un asesor conectado con menos casos que su tope puede recibir uno nuevo.
- Si no hay nadie disponible, el caso queda "en cola" y el bot avisa.
- Al liberarse un caso (o al conectarse alguien) se reparte la cola.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Advisor, Handoff

logger = logging.getLogger(__name__)

ABIERTOS = ("pending", "taken")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def office_open(moment: datetime | None = None) -> bool:
    """¿Estamos en horario de atención?"""
    if not settings.office_hours_enabled:
        return True
    actual = (moment or _ahora()).astimezone()
    dias = {
        int(d.strip())
        for d in (settings.office_hours_days or "1,2,3,4,5").split(",")
        if d.strip().isdigit()
    }
    if actual.isoweekday() not in dias:
        return False
    try:
        inicio = time.fromisoformat(settings.office_hours_start)
        fin = time.fromisoformat(settings.office_hours_end)
    except ValueError:
        return True
    return inicio <= actual.time() <= fin


def is_online(advisor: Advisor, moment: datetime | None = None) -> bool:
    if not advisor.active or advisor.last_seen_at is None:
        return False
    visto = advisor.last_seen_at
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=timezone.utc)
    limite = (moment or _ahora()) - timedelta(
        seconds=settings.presence_timeout_seconds
    )
    return visto >= limite


async def open_cases(session: AsyncSession, advisor: Advisor) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(
                Handoff.assigned_to == advisor.display_name,
                Handoff.status.in_(ABIERTOS),
            )
        )
        or 0
    )


async def heartbeat(session: AsyncSession, advisor: Advisor) -> dict:
    """Marca al asesor como conectado y reparte la cola si hay lugar."""
    advisor.last_seen_at = _ahora()
    await session.commit()
    asignados = await assign_queued(session)
    return {
        "ok": True,
        "status": await status_of(session, advisor),
        "assigned_now": asignados,
    }


async def status_of(session: AsyncSession, advisor: Advisor) -> str:
    if not is_online(advisor):
        return "offline"
    return "busy" if await open_cases(session, advisor) >= advisor.max_cases else "online"


async def available_advisors(session: AsyncSession) -> list[Advisor]:
    """Asesores conectados con capacidad, del menos cargado al más."""
    asesores = (
        await session.scalars(select(Advisor).where(Advisor.active.is_(True)))
    ).all()
    disponibles: list[tuple[int, Advisor]] = []
    for asesor in asesores:
        if not is_online(asesor):
            continue
        abiertos = await open_cases(session, asesor)
        if abiertos < asesor.max_cases:
            disponibles.append((abiertos, asesor))
    disponibles.sort(key=lambda par: (par[0], par[1].created_at or _ahora()))
    return [asesor for _abiertos, asesor in disponibles]


async def pick_advisor(session: AsyncSession) -> Advisor | None:
    disponibles = await available_advisors(session)
    return disponibles[0] if disponibles else None


async def assign_queued(session: AsyncSession, limit: int = 20) -> int:
    """Asigna los casos en cola a quien tenga lugar (primero en llegar)."""
    pendientes = (
        await session.scalars(
            select(Handoff)
            .where(Handoff.status == "queued")
            .order_by(Handoff.created_at)
            .limit(limit)
        )
    ).all()
    asignados = 0
    for caso in pendientes:
        asesor = await pick_advisor(session)
        if asesor is None:
            break
        caso.assigned_to = asesor.display_name
        caso.status = "pending"
        asignados += 1
        await session.commit()
        logger.info("Caso %s asignado a %s", caso.id, asesor.display_name)
    return asignados


async def presence_summary(session: AsyncSession) -> dict:
    asesores = (
        await session.scalars(
            select(Advisor).where(Advisor.active.is_(True)).order_by(Advisor.display_name)
        )
    ).all()
    filas = []
    for asesor in asesores:
        abiertos = await open_cases(session, asesor)
        filas.append(
            {
                "id": asesor.id,
                "username": asesor.username,
                "display_name": asesor.display_name,
                "status": "offline"
                if not is_online(asesor)
                else ("busy" if abiertos >= asesor.max_cases else "online"),
                "open_cases": abiertos,
                "max_cases": asesor.max_cases,
                "on_duty": bool(asesor.on_duty),
                "last_seen_at": asesor.last_seen_at.isoformat()
                if asesor.last_seen_at
                else None,
            }
        )
    en_cola = int(
        await session.scalar(
            select(func.count()).select_from(Handoff).where(Handoff.status == "queued")
        )
        or 0
    )
    return {
        "office_open": office_open(),
        "advisors": filas,
        "online": sum(1 for f in filas if f["status"] == "online"),
        "busy": sum(1 for f in filas if f["status"] == "busy"),
        "offline": sum(1 for f in filas if f["status"] == "offline"),
        "queued": en_cola,
    }
