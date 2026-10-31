"""Genera promociones locales desde el precio de lista del catálogo VTEX.

El catálogo guarda en ``attributes.list_price`` el precio de lista y en
``attributes.vtex_current_price`` el precio vigente. Esta rutina deja
``CatalogItem.price`` como precio de lista y crea una fila de
``ProductPromotion`` con el precio vigente y el descuento.

No consulta VTEX: es una pasada local sobre el catálogo ya sincronizado.

Uso:
    python -m scripts.sync_vtex_promotions
    python -m scripts.sync_vtex_promotions --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select, text

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import CatalogItem, ProductPromotion

logger = logging.getLogger("sync_vtex_promotions")


async def sync(dry_run: bool = False) -> None:
    await init_db()
    candidates: list[tuple[CatalogItem, Decimal, Decimal, Decimal]] = []

    async with SessionLocal() as session:
        # SQLite necesita temp en memoria para el INSERT masivo. PostgreSQL
        # no acepta PRAGMA.
        if settings.database_url.startswith("sqlite"):
            await session.execute(text("PRAGMA temp_store=MEMORY"))
            await session.execute(text("PRAGMA busy_timeout=10000"))
        items = (
            await session.scalars(
                select(CatalogItem).where(CatalogItem.active.is_(True))
            )
        ).all()

        for item in items:
            attributes = dict(item.attributes or {})
            try:
                list_price = Decimal(str(attributes.get("list_price") or 0))
                current_price = Decimal(
                    str(attributes.get("vtex_current_price") or item.price or 0)
                )
            except Exception:  # noqa: BLE001
                continue

            if list_price <= 0 or current_price <= 0 or list_price <= current_price:
                continue

            discount = (
                (list_price - current_price) / list_price * 100
            ).quantize(Decimal("0.01"))
            candidates.append((item, current_price, list_price, discount))

        logger.info("Artículos con descuento VTEX: %s", len(candidates))
        if dry_run:
            return

        await session.execute(
            delete(ProductPromotion).where(
                ProductPromotion.source == "vtex_catalog"
            )
        )
        await session.commit()

        now = datetime.now(timezone.utc)
        batch_size = 50
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            for item, current_price, list_price, discount in batch:
                attributes = dict(item.attributes or {})
                attributes["vtex_current_price"] = str(current_price)
                attributes["vtex_list_price"] = str(list_price)
                item.attributes = attributes
                item.price = list_price

                valid_to = None
                raw_valid_to = attributes.get("price_valid_until")
                if raw_valid_to:
                    try:
                        valid_to = datetime.fromisoformat(
                            str(raw_valid_to).replace("Z", "+00:00")
                        ).date()
                    except ValueError:
                        valid_to = None

                session.add(
                    ProductPromotion(
                        sku=item.sku,
                        price=current_price,
                        discount_percent=discount,
                        valid_from=None,
                        valid_to=valid_to,
                        tier_quantity=None,
                        price_list=1,
                        source="vtex_catalog",
                        synced_at=now,
                    )
                )
            await session.commit()
            logger.info(
                "Promociones VTEX guardadas: %s/%s",
                min(start + batch_size, len(candidates)),
                len(candidates),
            )

        logger.info("Promociones VTEX creadas: %s", len(candidates))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea promociones locales desde el catálogo VTEX"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(sync(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
