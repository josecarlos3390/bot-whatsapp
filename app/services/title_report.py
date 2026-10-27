"""Propuesta de títulos cortos para el catálogo.

WhatsApp y el catálogo nativo muestran el título en poco espacio. Muchos
títulos traen la descripción comercial seguida del nombre técnico repetido
en mayúsculas. La propuesta conserva la parte comercial y recorta en una
palabra completa.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogItem
from .catalog_quality import MAX_NOMBRE, _partes_titulo

MIN_NOMBRE = 25


def shorten(name: str, limit: int = MAX_NOMBRE) -> str:
    """Versión corta del título, sin cortar palabras."""
    texto = re.sub(r"\s+", " ", (name or "").strip())
    if len(texto) <= limit:
        return texto
    partes = _partes_titulo(texto)
    if partes is not None:
        comercial, _tecnica = partes
        # Si la parte comercial ya alcanza, se usa tal cual.
        if MIN_NOMBRE <= len(comercial) <= limit:
            return comercial
        if len(comercial) > limit:
            texto = comercial
    recorte = texto[:limit].rstrip(" ,-–—/")
    if " " in recorte:
        recorte = recorte.rsplit(" ", 1)[0].rstrip(" ,-–—/")
    return recorte or texto[:limit]


async def title_proposals(
    session: AsyncSession, limit: int | None = None
) -> list[dict]:
    """Títulos que superan el máximo, con una propuesta más corta."""
    filas = (
        await session.scalars(
            select(CatalogItem)
            .where(CatalogItem.active.is_(True))
            .order_by(CatalogItem.name)
        )
    ).all()
    propuestas = []
    for item in filas:
        nombre = item.name or ""
        if len(nombre) <= MAX_NOMBRE:
            continue
        propuestas.append(
            {
                "id": item.sku,
                "title": item.name,
                "length": len(nombre),
                "proposed_title": shorten(nombre),
                "proposed_length": len(shorten(nombre)),
                "brand": item.brand or "",
                "category": item.category or "",
            }
        )
        if limit and len(propuestas) >= limit:
            break
    return propuestas
