"""Validar la búsqueda libre de VTEX (sinónimos de la tienda).

Se corre cuando el PaaS publique ``/api/vtex/search``.

Uso:
    python -m scripts.validar_busqueda_vtex
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.db import SessionLocal
from app.services import vtex_search


async def main() -> int:
    print("Configuración")
    print(f"  · VTEX_SEARCH_ENABLED = {settings.vtex_search_enabled}")
    print(f"  · PaaS                = {settings.sap_paas_url}")
    if not settings.vtex_search_enabled:
        print("\nLa búsqueda está apagada: activala con VTEX_SEARCH_ENABLED=true")
        return 1

    vtex_search.olvidar()
    casos = ["fumigador", "bebote", "muñeca", "taladro", "hidrolavadora"]
    print("\nConsultas")
    fallos = 0
    async with SessionLocal() as session:
        for consulta in casos:
            items = await vtex_search.buscar(consulta, limite=5)
            if not items:
                print(f"  ✗ {consulta:<14} sin resultados")
                fallos += 1
                continue
            print(f"  ✓ {consulta:<14} {len(items)} → {items[0]['name'][:40]}")
            # Se compara con el catálogo local para ver si aporta algo nuevo.
            from app.services import catalog

            local = await catalog.search_items(session, consulta, limit=5)
            if len(items) > len(local):
                print(
                    f"      aporta {len(items) - len(local)} resultado(s) "
                    "que el catálogo local no tenía"
                )

    if fallos:
        print(f"\n{fallos} consulta(s) sin resultados. ¿Está publicado el endpoint?")
        return 1
    print("\nBúsqueda de VTEX validada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
