"""Genera un borrador de mapa de ocasiones con DeepSeek.

No modifica el mapa aprobado. Escribe knowledge/occasions.draft.json para que
una persona lo revise antes de copiarlo a knowledge/occasions.json.

Uso:
    python -m scripts.generate_occasions
    python -m scripts.generate_occasions --events halloween,baby shower
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import CatalogItem

DRAFT = Path("knowledge/occasions.draft.json")
LIVE = Path("knowledge/occasions.json")

PROMPT = """Sos un curador de categorías para una tienda de hogar en Bolivia.
Para cada ocasión, proponé términos de búsqueda genéricos que podrían existir
en un catálogo de hogar, ferretería, muebles, decoración y línea blanca.

Devolvé SOLO JSON con esta forma:
{
  "evento": {
    "label": "Nombre visible",
    "aliases": ["formas en que un cliente lo escribiría"],
    "direct": ["términos directos para buscar en el catálogo"],
    "exclude": ["palabras que no deben mezclarse"],
    "exclude_categories": ["categorías que no aplican"],
    "bridges": [
      {"label": "alternativa natural", "terms": ["términos válidos"]}
    ]
  }
}

Reglas:
- No inventes productos, marcas, precios ni stock.
- Los términos deben ser genéricos y buscables.
- Máximo 8 términos por lista.
- Si la ocasión no tiene productos directos, usá bridges hacia algo que sí
  se venda y tenga relación natural.
- No agregues instrucciones para el bot.
"""


def _clean(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:8]:
        text = str(item).strip().lower()
        if 2 <= len(text) <= 80 and text not in result:
            result.append(text)
    return result


async def generate(events: list[str]) -> dict:
    if not settings.deepseek_api_key:
        raise SystemExit("DEEPSEEK_API_KEY no está configurada")
    async with SessionLocal() as session:
        categories = list(
            (
                await session.scalars(
                    select(CatalogItem.category)
                    .where(CatalogItem.active.is_(True))
                    .distinct()
                    .limit(60)
                )
            ).all()
        )
    client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    completion = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": (
                    "Ocasiones: "
                    + ", ".join(events)
                    + "\nCategorías reales: "
                    + ", ".join(str(c) for c in categories if c)
                ),
            },
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )
    data = json.loads(completion.choices[0].message.content or "{}")
    cleaned = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        direct = _clean(value.get("direct"))
        bridges = []
        for bridge in value.get("bridges") or []:
            if not isinstance(bridge, dict):
                continue
            terms = _clean(bridge.get("terms"))
            if terms:
                bridges.append(
                    {
                        "label": str(bridge.get("label") or "alternativa")[:80],
                        "terms": terms,
                    }
                )
        if not direct and not bridges:
            continue
        cleaned[key] = {
            "label": str(value.get("label") or key)[:80],
            "aliases": _clean(value.get("aliases")),
            "direct": direct,
            "exclude": _clean(value.get("exclude")),
            "exclude_categories": [
                str(item).upper() for item in _clean(value.get("exclude_categories"))
            ],
            "bridges": bridges,
        }
    await client.close()
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--events",
        default="halloween,navidad,día de la madre,día del padre,baby shower,mudanza,parrilla,vuelta a clases",
    )
    args = parser.parse_args()
    events = [item.strip() for item in args.events.split(",") if item.strip()]
    data = asyncio.run(generate(events))
    if not data:
        raise SystemExit("DeepSeek no devolvió un borrador válido")
    DRAFT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Borrador escrito en {DRAFT}")
    print("Revisalo y, si está aprobado, copialo a knowledge/occasions.json")


if __name__ == "__main__":
    main()
