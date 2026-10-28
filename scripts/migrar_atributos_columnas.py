"""Columnas propias para tipo, color y material del catálogo.

Antes vivían dentro del JSON `attributes`: consultarlos era caro y no se
podían indexar. Ahora son columnas, con el JSON como respaldo.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from app.db import SessionLocal, engine


async def migrar() -> None:
    columnas = (
        ("product_type", "VARCHAR(80)"),
        ("color", "VARCHAR(60)"),
        ("material", "VARCHAR(60)"),
        ("keywords_source", "VARCHAR(20)"),
        ("keywords_synced_at", "DATETIME"),
    )
    async with engine.begin() as conn:
        for nombre, tipo in columnas:
            try:
                await conn.execute(
                    text(f"ALTER TABLE catalog_items ADD COLUMN {nombre} {tipo}")
                )
                print(f"columna agregada: {nombre}")
            except Exception as exc:  # noqa: BLE001 - ya existe
                print(f"columna {nombre}: {str(exc)[:60]}")
        for nombre in ("product_type", "color", "keywords_source"):
            try:
                await conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_catalog_items_{nombre} "
                        f"ON catalog_items ({nombre})"
                    )
                )
            except Exception as exc:  # noqa: BLE001
                print(f"índice {nombre}: {str(exc)[:60]}")


async def rellenar() -> int:
    """Copia los valores del JSON a las columnas nuevas."""
    actualizados = 0
    async with SessionLocal() as session:
        filas = (
            await session.execute(
                text(
                    "SELECT id, attributes, product_type, color, material, "
                    "keywords_source FROM catalog_items"
                )
            )
        ).all()
        for (
            ident,
            attributes,
            tipo,
            color,
            material,
            source,
        ) in filas:
            if isinstance(attributes, str):
                try:
                    attributes = json.loads(attributes)
                except ValueError:
                    attributes = {}
            if not isinstance(attributes, dict):
                continue
            specs = attributes.get("specs")
            specs = specs if isinstance(specs, dict) else {}
            nuevo_tipo = tipo or attributes.get("product_type") or specs.get("Tipo")
            nuevo_color = color or attributes.get("color") or specs.get("Color")
            nuevo_material = (
                material or attributes.get("material") or specs.get("Material")
            )
            nueva_fuente = source or attributes.get("keywords_source")
            sincronizado = attributes.get("keywords_synced_at")
            if (
                nuevo_tipo == tipo
                and nuevo_color == color
                and nuevo_material == material
                and nueva_fuente == source
            ):
                continue
            await session.execute(
                text(
                    "UPDATE catalog_items SET product_type = :t, color = :c, "
                    "material = :m, keywords_source = :s, "
                    "keywords_synced_at = :k WHERE id = :id"
                ),
                {
                    "t": str(nuevo_tipo)[:80] if nuevo_tipo else None,
                    "c": str(nuevo_color)[:60] if nuevo_color else None,
                    "m": str(nuevo_material)[:60] if nuevo_material else None,
                    "s": str(nueva_fuente)[:20] if nueva_fuente else None,
                    "k": sincronizado,
                    "id": ident,
                },
            )
            actualizados += 1
        await session.commit()
    return actualizados


async def main() -> int:
    await migrar()
    total = await rellenar()
    print(f"artículos actualizados: {total}")
    async with SessionLocal() as session:
        for columna in ("product_type", "color", "material"):
            valor = await session.scalar(
                text(f"SELECT COUNT(*) FROM catalog_items WHERE {columna} IS NOT NULL")
            )
            print(f"con {columna}: {valor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
