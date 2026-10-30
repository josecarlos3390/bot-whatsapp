"""Limpiar filas huérfanas: las que apuntan a un padre que ya no existe.

Aparecen cuando se borran conversaciones a mano con SQL. No rompen al bot,
pero impiden restaurar una copia: al recargar, las claves foráneas fallan.

Uso:
    python -m scripts.limpiar_huerfanos            # solo informa
    python -m scripts.limpiar_huerfanos --confirmar
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, exists, func, select

from app import models  # noqa: F401  (registra las tablas)
from app.db import Base, SessionLocal


def _relaciones() -> list[tuple[str, str, str, str]]:
    """(tabla hija, columna, tabla padre, columna padre) por cada FK."""
    salida: list[tuple[str, str, str, str]] = []
    for tabla in Base.metadata.sorted_tables:
        for fk in tabla.foreign_keys:
            salida.append(
                (
                    tabla.name,
                    fk.parent.name,
                    fk.column.table.name,
                    fk.column.name,
                )
            )
    return salida


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    args = parser.parse_args()

    tablas = {tabla.name: tabla for tabla in Base.metadata.sorted_tables}
    total = 0
    async with SessionLocal() as session:
        for hija, columna, padre, columna_padre in _relaciones():
            tabla_hija = tablas[hija]
            tabla_padre = tablas[padre]
            condicion = ~exists().where(
                getattr(tabla_padre.c, columna_padre)
                == getattr(tabla_hija.c, columna)
            )
            cantidad = await session.scalar(
                select(func.count())
                .select_from(tabla_hija)
                .where(condicion)
            )
            if not cantidad:
                continue
            total += cantidad
            print(f"{hija}.{columna} sin {padre}: {cantidad}")
            if args.confirmar:
                await session.execute(
                    delete(tabla_hija).where(condicion)
                )
        if args.confirmar:
            await session.commit()
            print(f"\nborradas: {total}")
        else:
            print(f"\ntotal de huérfanas: {total} (modo informe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
