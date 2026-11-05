"""Quitar del catálogo los artículos que dejaron las pruebas.

Los scripts de depuración a veces crean artículos en la base real (no en la
de test). Este script borra solo los que tienen SKU de prueba conocidos.

Uso:
    python -m scripts.limpiar_articulos_prueba            # muestra qué borraría
    python -m scripts.limpiar_articulos_prueba --borrar   # borra
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import CartItem, CatalogItem

# SKU que solo existen en pruebas y depuraciones.
SKUS_DE_PRUEBA = (
    "VAC-TV",
    "DBG-1",
    "LINK-1",
    "FIN-1",
    "EST-ELSA",
    "CARR-1",
    "MK-1",
    "MC-1",
    "AUT-1",
    "MUN-1",
    "PULV-1",
    "TAL-9",
    "CHK-001",
    "REM-001",
    "FILT-001",
    "CARD-001",
    "CARD-002",
    "CARD-003",
)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--borrar", action="store_true")
    args = parser.parse_args()

    async with SessionLocal() as session:
        filas = (
            await session.scalars(
                select(CatalogItem).where(
                    CatalogItem.sku.in_(SKUS_DE_PRUEBA)
                )
            )
        ).all()
        if not filas:
            print("No hay artículos de prueba en el catálogo.")
            return 0

        print(f"Artículos de prueba encontrados: {len(filas)}\n")
        for fila in filas:
            print(
                f"  · {fila.sku:<14} {fila.name[:44]:<44} "
                f"activo={fila.active} stock={fila.stock}"
            )

        if not args.borrar:
            print("\nSimulación: no se borró nada. Para borrar: --borrar")
            return 0

        for fila in filas:
            await session.execute(
                delete(CartItem).where(CartItem.sku == fila.sku)
            )
            await session.delete(fila)
        await session.commit()
        print(f"\nBorrados: {len(filas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
