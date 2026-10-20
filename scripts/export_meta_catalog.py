"""Exporta el catálogo local a CSV para Commerce Manager.

Uso:
    python -m scripts.export_meta_catalog --out meta_catalog.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.services.native_commerce import catalog_feed

logger = logging.getLogger("export_meta_catalog")

FIELDS = [
    "id",
    "title",
    "description",
    "availability",
    "condition",
    "price",
    "link",
    "image_link",
    "brand",
    "category",
]


async def run(out: Path, limit: int | None = None) -> None:
    async with SessionLocal() as session:
        rows, skipped = await catalog_feed(session, limit=limit)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(
        "Exportados %s productos (%s sin imagen omitidos) a %s",
        len(rows),
        skipped,
        out,
    )
    if not settings.meta_catalog_link_base:
        logger.warning(
            "META_CATALOG_LINK_BASE vacío: el feed tendrá link vacío y Meta puede rechazarlo"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta catálogo para Meta")
    parser.add_argument("--out", default="meta_catalog.csv")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(run(Path(args.out), limit=args.limit))


if __name__ == "__main__":
    main()
