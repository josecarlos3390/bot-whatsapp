"""KPIs de atención: qué mide a cada asesor y al equipo.

Los números salen de los casos (handoffs), sus eventos y las encuestas:
- Cuántos tomó, resolvió, reabrió y devolvió al bot.
- Cuánto tardó en la primera respuesta y en resolver.
- Si cumplió el SLA (resolver dentro del tiempo pactado).
- Cuántos casos escalados atendió.
- Satisfacción del cliente (encuesta).
- Carga actual (casos abiertos).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Advisor, Handoff, HandoffEvent, HandoffSurvey

logger = logging.getLogger(__name__)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _minutos(desde: datetime | None, hasta: datetime | None) -> float | None:
    desde, hasta = _aware(desde), _aware(hasta)
    if desde is None or hasta is None:
        return None
    return round((hasta - desde).total_seconds() / 60, 1)


async def advisor_kpis(session: AsyncSession, days: int = 30) -> dict:
    dias = max(int(days), 1)
    desde = datetime.now(timezone.utc) - timedelta(days=dias)

    asesores = (
        await session.scalars(select(Advisor).where(Advisor.active.is_(True)))
    ).all()
    nombres = {a.username: a.display_name for a in asesores}

    casos = (
        await session.scalars(
            select(Handoff).where(Handoff.created_at >= desde)
        )
    ).all()
    casos_por_id = {c.id: c for c in casos}

    eventos = (
        await session.scalars(
            select(HandoffEvent)
            .where(HandoffEvent.created_at >= desde)
            .order_by(HandoffEvent.created_at)
        )
    ).all()

    encuestas = {
        fila.handoff_id: fila
        for fila in (
            await session.scalars(
                select(HandoffSurvey).where(HandoffSurvey.created_at >= desde)
            )
        ).all()
        if fila.rating is not None
    }

    filas: dict[str, dict] = {}

    def fila_de(usuario: str) -> dict:
        return filas.setdefault(
            usuario,
            {
                "username": usuario,
                "advisor": nombres.get(usuario, usuario),
                "taken": 0,
                "resolved": 0,
                "reopened": 0,
                "returned": 0,
                "replies": 0,
                "escalated": 0,
                "sla_ok": 0,
                "sla_total": 0,
                "_response": [],
                "_resolution": [],
                "_ratings": [],
            },
        )

    for evento in eventos:
        if not evento.advisor:
            continue
        fila = fila_de(evento.advisor)
        caso = casos_por_id.get(evento.handoff_id)
        if evento.action == "taken":
            fila["taken"] += 1
        elif evento.action == "resolved":
            fila["resolved"] += 1
            if caso is not None:
                minutos = _minutos(caso.created_at, evento.created_at)
                if minutos is not None:
                    fila["_resolution"].append(minutos)
                    fila["sla_total"] += 1
                    if minutos <= settings.handoff_sla_minutes:
                        fila["sla_ok"] += 1
        elif evento.action == "reopened":
            fila["reopened"] += 1
        elif evento.action == "returned":
            fila["returned"] += 1
        elif evento.action in {"replied", "note"}:
            fila["replies"] += 1

    for caso in casos:
        if not caso.assigned_to:
            continue
        usuario = next(
            (u for u, nombre in nombres.items() if nombre == caso.assigned_to),
            caso.assigned_to,
        )
        fila = fila_de(usuario)
        if caso.escalated_at is not None:
            fila["escalated"] += 1
        encuesta = encuestas.get(caso.id)
        if encuesta is not None:
            fila["_ratings"].append(encuesta.rating)

    # Primera respuesta: desde que se creó el caso hasta el primer "replied".
    primera: dict[str, datetime] = {}
    for evento in eventos:
        if evento.action != "replied" or not evento.advisor:
            continue
        caso = casos_por_id.get(evento.handoff_id)
        if caso is None:
            continue
        if evento.handoff_id not in primera:
            primera[evento.handoff_id] = evento.created_at
            minutos = _minutos(caso.created_at, evento.created_at)
            if minutos is not None:
                fila_de(evento.advisor)["_response"].append(minutos)

    salida = []
    for fila in filas.values():
        respuestas = fila.pop("_response")
        resoluciones = fila.pop("_resolution")
        ratings = fila.pop("_ratings")
        fila["avg_response_minutes"] = (
            round(sum(respuestas) / len(respuestas), 1) if respuestas else None
        )
        fila["avg_resolution_minutes"] = (
            round(sum(resoluciones) / len(resoluciones), 1)
            if resoluciones
            else None
        )
        fila["sla_rate"] = (
            round(fila["sla_ok"] / fila["sla_total"] * 100, 1)
            if fila["sla_total"]
            else None
        )
        fila["satisfaction"] = (
            round(sum(ratings) / len(ratings), 2) if ratings else None
        )
        fila["surveys"] = len(ratings)
        salida.append(fila)

    salida.sort(key=lambda f: (-f["resolved"], -f["taken"]))

    abiertos = [c for c in casos if c.status in ("queued", "pending", "taken")]
    escalados = [c for c in abiertos if c.escalated_at is not None]
    equipo = {
        "taken": sum(f["taken"] for f in salida),
        "resolved": sum(f["resolved"] for f in salida),
        "reopened": sum(f["reopened"] for f in salida),
        "escalated": len(escalados),
        "queued": sum(1 for c in casos if c.status == "queued"),
        "pending": sum(1 for c in casos if c.status == "pending"),
        "taken_now": sum(1 for c in casos if c.status == "taken"),
        "escalated_now": len(escalados),
        "sla_rate": (
            round(
                sum(f["sla_ok"] for f in salida)
                / max(sum(f["sla_total"] for f in salida), 1)
                * 100,
                1,
            )
            if any(f["sla_total"] for f in salida)
            else None
        ),
        "satisfaction": (
            round(
                sum(
                    f["satisfaction"] * f["surveys"]
                    for f in salida
                    if f["satisfaction"] is not None
                )
                / max(sum(f["surveys"] for f in salida), 1),
                2,
            )
            if any(f["surveys"] for f in salida)
            else None
        ),
        "advisors": len(salida),
    }

    return {"days": dias, "since": desde.isoformat(), "advisors": salida, "team": equipo}
