"""Migrar los datos de SQLite a PostgreSQL.

Uso:
    python -m scripts.migrar_a_postgres --destino "postgresql+asyncpg://usuario:clave@127.0.0.1:5434/roho_bot"
    python -m scripts.migrar_a_postgres --destino "..." --solo-validar

Qué hace:
1. Crea el esquema en el destino.
2. Copia las tablas en orden de dependencia.
3. Compara la cantidad de filas de origen y destino.

No toca la base de origen: se puede correr las veces que haga falta.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401  (registra todas las tablas)
from app.config import settings
from app.db import Base

# Orden por dependencias (padres primero).
ORDEN = [
    "contacts",
    "conversations",
    "conversation_states",
    "conversation_flows",
    "conversation_guards",
    "conversation_recommendations",
    "conversation_summaries",
    "messages",
    "customer_profiles",
    "customer_candidates",
    "customer_facts",
    "carts",
    "cart_items",
    "orders",
    "order_items",
    "payments",
    "payment_events",
    "purchase_history",
    "purchase_history_lines",
    "catalog_items",
    "product_images",
    "product_promotions",
    "product_sales_stats",
    "missing_requests",
    "query_learning",
    "semantic_cache",
    "webhook_events",
    "handoffs",
    "handoff_events",
    "handoff_notes",
    "handoff_reads",
    "handoff_surveys",
    "advisors",
    "feedback_requests",
    "customer_feedback",
    "funnel_events",
    "area_rules",
    "area_rule_versions",
    "area_users",
    "occasions",
    "sap_event_inbox",
]


def _tablas() -> list:
    """Tablas de la metadata, en el orden definido."""
    existentes = {tabla.name: tabla for tabla in Base.metadata.sorted_tables}
    ordenadas = [existentes[nombre] for nombre in ORDEN if nombre in existentes]
    resto = [
        tabla
        for nombre, tabla in existentes.items()
        if nombre not in ORDEN
    ]
    return ordenadas + resto


async def limpiar(sesion) -> None:
    """Vacía el destino para poder repetir la migración."""
    from sqlalchemy import text as _text

    for tabla in reversed(_tablas()):
        await sesion.execute(
            _text(f'TRUNCATE TABLE "{tabla.name}" CASCADE')
        )
    await sesion.commit()


async def migrar(
    destino: str,
    lote: int = 500,
    sin_fks: bool = False,
    vaciar: bool = False,
) -> int:
    origen = create_async_engine(settings.database_url)
    destino_engine = create_async_engine(destino)
    origen_sesion = async_sessionmaker(origen, expire_on_commit=False)
    destino_sesion = async_sessionmaker(destino_engine, expire_on_commit=False)

    print("creando esquema en el destino…")
    async with destino_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if vaciar:
        print("vaciando el destino…")
        async with destino_sesion() as limpiador:
            await limpiar(limpiador)

    total = 0
    for tabla in _tablas():
        async with origen_sesion() as lector:
            filas = (await lector.execute(select(tabla))).mappings().all()
        if not filas:
            print(f"  {tabla.name:<28} 0")
            continue
        datos = [dict(fila) for fila in filas]
        async with destino_sesion() as escritor:
            if sin_fks:
                # La base de origen puede tener huérfanos (conversaciones
                # borradas a mano). Se copia tal cual y se avisa al final.
                await escritor.execute(
                    text("SET session_replication_role = replica")
                )
            for inicio in range(0, len(datos), lote):
                await escritor.execute(
                    insert(tabla), datos[inicio : inicio + lote]
                )
            await escritor.commit()
        total += len(datos)
        print(f"  {tabla.name:<28} {len(datos)}")

    await origen.dispose()
    await destino_engine.dispose()
    print(f"\nfilas copiadas: {total}")
    return total


async def validar(destino: str) -> int:
    origen = create_async_engine(settings.database_url)
    destino_engine = create_async_engine(destino)
    origen_sesion = async_sessionmaker(origen, expire_on_commit=False)
    destino_sesion = async_sessionmaker(destino_engine, expire_on_commit=False)
    diferencias = 0
    for tabla in _tablas():
        async with origen_sesion() as lector:
            en_origen = await lector.scalar(
                select(func.count()).select_from(tabla)
            )
        async with destino_sesion() as escritor:
            en_destino = await escritor.scalar(
                select(func.count()).select_from(tabla)
            )
        if (en_origen or 0) != (en_destino or 0):
            diferencias += 1
            print(
                f"  DIFERENCIA {tabla.name}: origen {en_origen} | destino {en_destino}"
            )
    await origen.dispose()
    await destino_engine.dispose()
    if diferencias == 0:
        print("validación: todas las tablas coinciden")
    return diferencias


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destino", required=True)
    parser.add_argument("--solo-validar", action="store_true")
    parser.add_argument(
        "--limpiar",
        action="store_true",
        help="Vacía el destino antes de copiar.",
    )
    parser.add_argument(
        "--sin-fks",
        action="store_true",
        help="Copia sin verificar claves foráneas (origen con huérfanos).",
    )
    args = parser.parse_args()

    print(f"origen: {settings.database_url}")
    print(f"destino: {args.destino}\n")
    if args.solo_validar:
        return 1 if await validar(args.destino) else 0
    await migrar(
        args.destino, sin_fks=args.sin_fks, vaciar=args.limpiar
    )
    print()
    return 1 if await validar(args.destino) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
