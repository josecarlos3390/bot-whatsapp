"""CRUD y resolución de campañas/ocasiones administrables."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Occasion
from . import occasions as static_occasions


class OccasionError(ValueError):
    pass


def _clean_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item).strip().lower()
        if 1 <= len(text) <= 80 and text not in result:
            result.append(text)
    return result


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return value[:80] or "ocasion"


def _validate(
    *,
    name: str,
    direct: list[str],
    bridges: list[dict],
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    if not (name or "").strip():
        raise OccasionError("La ocasión necesita un nombre")
    if not direct and not bridges:
        raise OccasionError("Agregá términos directos o una alternativa")
    if valid_from and valid_to and valid_to < valid_from:
        raise OccasionError("La fecha final no puede ser anterior a la inicial")


def to_dict(row: Occasion) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "aliases": row.aliases or [],
        "direct": row.direct or [],
        "exclude": row.exclude or [],
        "exclude_categories": row.exclude_categories or [],
        "bridges": row.bridges or [],
        "validity": validity_label(row),
        "area": row.area,
        "status": row.status,
        "priority": row.priority,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "version": row.version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _event(row: Occasion) -> dict:
    return {
        "label": row.name,
        "aliases": row.aliases or [row.name, row.slug],
        "direct": row.direct or [],
        "exclude": row.exclude or [],
        "exclude_categories": row.exclude_categories or [],
        "bridges": row.bridges or [],
        "validity": validity_label(row),
    }


async def alias_conflicts(
    session: AsyncSession,
    aliases: list[str],
    *,
    exclude_id: str | None = None,
) -> list[dict]:
    """Alias que ya usa otra ocasión activa (aviso, no bloqueo)."""
    wanted = {str(item).strip().lower() for item in aliases or [] if item}
    if not wanted:
        return []
    rows = await list_occasions(session)
    conflicts: list[dict] = []
    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        if row.status != "published":
            continue
        for alias in row.aliases or []:
            key = str(alias).strip().lower()
            if key and key in wanted:
                conflicts.append({"alias": key, "occasion": row.name})
    return conflicts


def validity_label(row: Occasion, today: date | None = None) -> str:
    """Texto corto de vigencia para el panel."""
    current = today or date.today()
    if row.status != "published":
        return "Borrador"
    if row.valid_from and current < row.valid_from:
        return f"Empieza el {row.valid_from.strftime('%d/%m')}"
    if row.valid_to and current > row.valid_to:
        return f"Terminó el {row.valid_to.strftime('%d/%m')}"
    if row.valid_to:
        return f"Vigente hasta el {row.valid_to.strftime('%d/%m')}"
    return "Vigente hoy"


async def list_occasions(
    session: AsyncSession,
    *,
    area: str | None = None,
    status: str | None = None,
) -> list[Occasion]:
    stmt = select(Occasion).order_by(
        Occasion.priority.desc(), Occasion.name
    )
    if area:
        stmt = stmt.where(Occasion.area == area)
    if status:
        stmt = stmt.where(Occasion.status == status)
    return list((await session.scalars(stmt)).all())


async def get_occasion(
    session: AsyncSession, occasion_id: str
) -> Occasion | None:
    return await session.get(Occasion, occasion_id)


async def create_occasion(
    session: AsyncSession,
    *,
    name: str,
    aliases: list[str],
    direct: list[str],
    exclude: list[str],
    exclude_categories: list[str],
    bridges: list[dict],
    area: str = "marketing",
    status: str = "draft",
    priority: int = 100,
    valid_from: date | None = None,
    valid_to: date | None = None,
    changed_by: str = "admin",
) -> Occasion:
    direct = _clean_list(direct)
    bridges = [
        {
            "label": str(item.get("label") or "alternativa")[:80],
            "terms": _clean_list(item.get("terms")),
        }
        for item in bridges
        if isinstance(item, dict)
    ]
    bridges = [item for item in bridges if item["terms"]]
    _validate(
        name=name,
        direct=direct,
        bridges=bridges,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    base_slug = _slug(name)
    slug = base_slug
    suffix = 2
    while await session.scalar(
        select(Occasion.id).where(Occasion.slug == slug)
    ):
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    row = Occasion(
        name=name.strip()[:120],
        slug=slug,
        aliases=_clean_list(aliases) or [_slug(name)],
        direct=direct,
        exclude=_clean_list(exclude),
        exclude_categories=[
            item.upper() for item in _clean_list(exclude_categories)
        ],
        bridges=bridges,
        area=area,
        status=status,
        priority=int(priority),
        valid_from=valid_from,
        valid_to=valid_to,
        version=1,
        created_by=changed_by,
        updated_by=changed_by,
    )
    session.add(row)
    await session.commit()
    return row


async def update_occasion(
    session: AsyncSession,
    row: Occasion,
    *,
    name: str,
    aliases: list[str],
    direct: list[str],
    exclude: list[str],
    exclude_categories: list[str],
    bridges: list[dict],
    area: str,
    status: str,
    priority: int,
    valid_from: date | None,
    valid_to: date | None,
    changed_by: str = "admin",
) -> Occasion:
    direct = _clean_list(direct)
    clean_bridges = [
        {
            "label": str(item.get("label") or "alternativa")[:80],
            "terms": _clean_list(item.get("terms")),
        }
        for item in bridges
        if isinstance(item, dict)
    ]
    clean_bridges = [item for item in clean_bridges if item["terms"]]
    _validate(
        name=name,
        direct=direct,
        bridges=clean_bridges,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    row.name = name.strip()[:120]
    row.aliases = _clean_list(aliases) or [row.slug]
    row.direct = direct
    row.exclude = _clean_list(exclude)
    row.exclude_categories = [
        item.upper() for item in _clean_list(exclude_categories)
    ]
    row.bridges = clean_bridges
    row.area = area
    row.status = status
    row.priority = int(priority)
    row.valid_from = valid_from
    row.valid_to = valid_to
    row.version += 1
    row.updated_by = changed_by
    await session.commit()
    return row


async def publish_occasion(
    session: AsyncSession, row: Occasion, *, changed_by: str = "admin"
) -> Occasion:
    row.status = "published"
    row.version += 1
    row.updated_by = changed_by
    await session.commit()
    return row


async def delete_occasion(session: AsyncSession, row: Occasion) -> None:
    await session.delete(row)
    await session.commit()


async def active_events(
    session: AsyncSession, today: date | None = None
) -> dict[str, dict]:
    today = today or date.today()
    rows = await list_occasions(session, status="published")
    rows = [
        row
        for row in rows
        if (row.valid_from is None or row.valid_from <= today)
        and (row.valid_to is None or today <= row.valid_to)
    ]
    if not rows:
        return static_occasions.EVENTS
    return {row.slug: _event(row) for row in rows}


async def resolve(
    session: AsyncSession, text: str
) -> tuple[str, dict] | tuple[None, None]:
    events = await active_events(session)
    aliases: list[tuple[str, str]] = []
    for key, event in events.items():
        for alias in event.get("aliases") or [event.get("label", key)]:
            aliases.append((str(alias).lower(), key))
    aliases.sort(key=lambda item: len(item[0]), reverse=True)
    folded = (text or "").lower()
    for alias, key in aliases:
        if alias and alias in folded:
            return key, events[key]
    return None, None


async def seed_examples(session: AsyncSession) -> int:
    added = 0
    for key, event in static_occasions.FALLBACK.items():
        if await session.scalar(select(Occasion.id).where(Occasion.slug == key)):
            continue
        session.add(
            Occasion(
                name=event["label"],
                slug=key,
                aliases=event.get("aliases") or [key],
                direct=event.get("direct") or [],
                exclude=event.get("exclude") or [],
                exclude_categories=event.get("exclude_categories") or [],
                bridges=event.get("bridges") or [],
                area="marketing",
                status="published",
                priority=100,
                version=1,
                created_by="seed",
                updated_by="seed",
            )
        )
        added += 1
    await session.commit()
    return added
