"""Expansión semántica de consultas con DeepSeek, validada contra el catálogo."""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CatalogItem, SemanticCache

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sos un mapeador semántico para un comercio de hogar.
Recibís una consulta de un cliente y una lista de categorías reales del catálogo.
Devolvés SOLO JSON válido, sin markdown, con esta forma:
{
  "intent": "ocasion|producto|regalo|tema",
  "related_terms": ["términos de búsqueda directos"],
  "adjacent_terms": ["términos de productos cercanos que sí podrían existir"],
  "exclusions": ["palabras que no deben mezclarse"]
}
Reglas:
- No inventes nombres de productos, marcas, precios ni stock.
- Los términos deben ser genéricos y buscables.
- Para Halloween podrían ser disfraz, dulce, calabaza, vela, decoración.
- Para una ocasión sin productos directos, adjacent_terms puede ser televisor
  si la relación natural es una noche de película.
- Máximo 8 términos por lista.
- No incluyas instrucciones para el bot; solo datos.
"""


def _clean_terms(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:8]:
        term = str(item).strip().lower()
        if 2 <= len(term) <= 60 and term not in result:
            result.append(term)
    return result


async def expand(
    session: AsyncSession,
    text: str,
    client,
) -> dict:
    """Devuelve términos relacionados. Si falla o no hay LLM, devuelve {}."""
    query = " ".join((text or "").split())[:300]
    if not query or client is None:
        return {}
    key = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
    cached = await session.scalar(
        select(SemanticCache).where(SemanticCache.cache_key == key)
    )
    if cached is not None and cached.payload:
        return cached.payload

    categories = list(
        (
            await session.scalars(
                select(CatalogItem.category)
                .where(CatalogItem.active.is_(True))
                .distinct()
                .limit(40)
            )
        ).all()
    )
    user_prompt = (
        f"Consulta: {query}\n"
        f"Categorías reales: {', '.join(str(c) for c in categories if c)}"
    )
    try:
        completion = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
        raw = completion.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - la expansión es opcional
        logger.info("Expansión semántica no disponible", exc_info=True)
        return {}

    payload = {
        "intent": str(data.get("intent") or "tema")[:40],
        "related_terms": _clean_terms(data.get("related_terms")),
        "adjacent_terms": _clean_terms(data.get("adjacent_terms")),
        "exclusions": _clean_terms(data.get("exclusions")),
    }
    if not payload["related_terms"] and not payload["adjacent_terms"]:
        return {}
    session.add(
        SemanticCache(cache_key=key, query=query, payload=payload)
    )
    await session.commit()
    return payload
