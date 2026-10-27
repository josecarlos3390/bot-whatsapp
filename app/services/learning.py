"""Aprendizaje de búsquedas: el bot recuerda cómo resolvió lo que no encontraba.

Flujo:
1. Antes de buscar, ``recall`` devuelve la consulta aprendida para ese término.
2. Si la búsqueda no encuentra nada, ``remember`` guarda la consulta que sí
   funcionó (interpretada por el modelo).
3. ``record_miss`` cuenta los términos que no se pudieron resolver, para que
   el equipo vea qué falta en el catálogo.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import QueryLearning

logger = logging.getLogger(__name__)


def normalize(text: str | None) -> str:
    valor = (text or "").strip().lower()
    valor = "".join(
        char
        for char in unicodedata.normalize("NFKD", valor)
        if not unicodedata.combining(char)
    )
    valor = re.sub(r"[^a-z0-9ñü ]", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()[:200]


async def recall(session: AsyncSession, text: str | None) -> str | None:
    """Consulta aprendida para ese término, si existe."""
    clave = normalize(text)
    if not clave:
        return None
    fila = await session.scalar(
        select(QueryLearning).where(QueryLearning.term == clave)
    )
    if fila is None or not fila.query:
        return None
    fila.hits += 1
    await session.commit()
    return fila.query


async def remember(
    session: AsyncSession,
    *,
    term: str,
    query: str,
    producto: str | None = None,
    atributos: list[str] | None = None,
    source: str = "ia",
) -> None:
    """Guarda (o actualiza) la consulta que resolvió ese término."""
    clave = normalize(term)
    if not clave or not query:
        return
    fila = await session.scalar(
        select(QueryLearning).where(QueryLearning.term == clave)
    )
    if fila is None:
        fila = QueryLearning(term=clave)
        session.add(fila)
    fila.query = query[:300]
    fila.producto = (producto or "")[:120] or None
    fila.atributos = " ".join(atributos or [])[:300] or None
    fila.source = source
    fila.hits = (fila.hits or 0) + 1
    await session.commit()
    logger.info("Búsqueda aprendida: %r -> %r", clave, query)


async def record_miss(session: AsyncSession, text: str | None) -> None:
    """Cuenta un término que no se pudo resolver."""
    clave = normalize(text)
    if not clave:
        return
    fila = await session.scalar(
        select(QueryLearning).where(QueryLearning.term == clave)
    )
    if fila is None:
        fila = QueryLearning(term=clave, misses=1)
        session.add(fila)
    else:
        fila.misses = (fila.misses or 0) + 1
    await session.commit()


async def summary(session: AsyncSession, limit: int = 10) -> dict:
    """Resumen para el panel: aprendidas y pendientes."""
    filas = (await session.scalars(select(QueryLearning))).all()
    aprendidas = [f for f in filas if f.query]
    pendientes = sorted(
        (f for f in filas if not f.query), key=lambda f: f.misses or 0, reverse=True
    )
    return {
        "aprendidas": len(aprendidas),
        "pendientes": len(pendientes),
        "top_pendientes": [
            {"term": f.term, "misses": f.misses or 0} for f in pendientes[:limit]
        ],
        "top_aprendidas": [
            {"term": f.term, "query": f.query, "hits": f.hits or 0}
            for f in sorted(aprendidas, key=lambda f: f.hits or 0, reverse=True)[:limit]
        ],
    }
