"""Importa imágenes de productos desde un CSV.

Formato:
    sku,image_url,alt,position,is_primary
    DCHDCRC200193,https://cdn.example.com/123.webp,Maceta Husik,1,true

Uso:
    python -m scripts.import_images --csv data/images.csv
    python -m scripts.import_images --csv data/images.csv --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import CatalogItem, ProductImage

logger = logging.getLogger("import_images")


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def run(csv_path: Path, *, dry_run: bool, source: str) -> None:
    await init_db()
    if not csv_path.exists():
        raise SystemExit(f"No existe {csv_path}")
    async with SessionLocal() as session:
        skus = set(
            (await session.scalars(select(CatalogItem.sku))).all()
        )
        added = updated = missing = invalid = 0
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                sku = (row.get("sku") or "").strip().upper()
                url = (row.get("image_url") or "").strip()
                if not sku or not url:
                    invalid += 1
                    continue
                if sku not in skus:
                    missing += 1
                    logger.warning("SKU no existe en catálogo: %s", sku)
                    continue
                if not _valid_url(url):
                    invalid += 1
                    logger.warning("URL inválida para %s: %s", sku, url)
                    continue
                position = int(row.get("position") or 1)
                is_primary = (row.get("is_primary") or "").lower() in {
                    "1", "true", "si", "sí", "yes"
                } or position == 1
                existing = await session.scalar(
                    select(ProductImage).where(
                        ProductImage.sku == sku,
                        ProductImage.url == url,
                    )
                )
                if existing is None:
                    session.add(
                        ProductImage(
                            sku=sku,
                            url=url,
                            alt=(row.get("alt") or "")[:200] or None,
                            position=position,
                            source=source,
                            is_primary=is_primary,
                            approved=True,
                        )
                    )
                    added += 1
                else:
                    existing.position = position
                    existing.alt = (row.get("alt") or "")[:200] or None
                    existing.is_primary = is_primary
                    existing.approved = True
                    updated += 1
                if is_primary:
                    catalog_item = await session.scalar(
                        select(CatalogItem).where(CatalogItem.sku == sku)
                    )
                    if catalog_item is not None:
                        catalog_item.image_url = url
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    logger.info(
        "Imágenes: nuevas=%s actualizadas=%s SKU faltantes=%s inválidas=%s",
        added,
        updated,
        missing,
        invalid,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/images.csv")
    parser.add_argument("--source", default="csv")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(
        run(Path(args.csv), dry_run=args.dry_run, source=args.source)
    )


if __name__ == "__main__":
    main()
