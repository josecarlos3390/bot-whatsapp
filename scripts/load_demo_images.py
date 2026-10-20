"""Carga imágenes referenciales por categoría para demo.

No son fotos reales del producto: son placeholders públicos por categoría.
Se marcan con source="demo" para poder reemplazarlas después.

Uso:
    python -m scripts.load_demo_images --limit 50
    python -m scripts.load_demo_images --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from urllib.parse import quote_plus

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import CatalogItem, ProductImage

logger = logging.getLogger("load_demo_images")


def _url(category: str | None) -> str:
    label = (category or "ROHO").strip() or "ROHO"
    return (
        "https://placehold.co/600x600/EEEEEE/333333/png?text="
        + quote_plus(label[:24])
    )


async def run(limit: int | None, *, dry_run: bool) -> None:
    await init_db()
    async with SessionLocal() as session:
        stmt = (
            select(CatalogItem)
            .where(
                CatalogItem.active.is_(True),
                CatalogItem.stock > 0,
                CatalogItem.image_url.is_(None),
            )
            .order_by(CatalogItem.stock.desc(), CatalogItem.name)
        )
        if limit:
            stmt = stmt.limit(limit)
        items = list((await session.scalars(stmt)).all())
        loaded = 0
        for item in items:
            existing = await session.scalar(
                select(ProductImage).where(ProductImage.sku == item.sku)
            )
            if existing is not None:
                continue
            url = _url(item.category)
            session.add(
                ProductImage(
                    sku=item.sku,
                    url=url,
                    alt=f"Imagen referencial: {item.category or 'ROHO'}",
                    position=1,
                    source="demo",
                    is_primary=True,
                    approved=True,
                )
            )
            item.image_url = url
            loaded += 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    logger.info("Imágenes referenciales cargadas: %s", loaded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(
        run(None if args.all else max(args.limit, 1), dry_run=args.dry_run)
    )


if __name__ == "__main__":
    main()
