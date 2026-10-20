"""Sincroniza precios especiales (promociones) de SAP al catálogo local.

Uso:
    python -m scripts.sync_promotions --limit 200
    python -m scripts.sync_promotions

No consulta SAP por cada mensaje: deja una tabla local para que el agente pueda
listar promociones vigentes y sugerir productos.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import delete

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import ProductPromotion
from app.sap import ServiceLayerSap

logger = logging.getLogger("sync_promotions")
PAGE_SIZE = 20


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def sync(limit: int | None = None) -> None:
    sap = ServiceLayerSap(session=None)  # type: ignore[arg-type]
    rows: list[ProductPromotion] = []
    today = date.today()
    scanned = 0
    try:
        last_code: str | None = None
        while True:
            flt = "CardCode eq '*1'"
            if last_code:
                escaped = last_code.replace("'", "''")
                flt += f" and ItemCode gt '{escaped}'"
            data = await sap.get(
                "SpecialPrices",
                params={
                    "$top": PAGE_SIZE,
                    "$orderby": "ItemCode",
                    "$filter": flt,
                    "$select": (
                        "ItemCode,CardCode,PriceListNum,"
                        "SpecialPriceDataAreas"
                    ),
                },
            )
            batch = data.get("value", [])
            if not batch:
                break
            for row in batch:
                for area in row.get("SpecialPriceDataAreas") or []:
                    price_list = int(
                        area.get("PriceListNo")
                        or row.get("PriceListNum")
                        or settings.sap_price_list
                    )
                    if price_list != settings.sap_price_list:
                        continue
                    valid_to = _as_date(area.get("Dateto"))
                    if valid_to is not None and valid_to < today:
                        continue
                    valid_from = _as_date(area.get("DateFrom"))
                    discount = Decimal(str(area.get("Discount") or 0))
                    special = Decimal(str(area.get("SpecialPrice") or 0))
                    if special > 0:
                        rows.append(
                            ProductPromotion(
                                sku=row["ItemCode"],
                                price=special,
                                discount_percent=discount,
                                valid_from=valid_from,
                                valid_to=valid_to,
                                tier_quantity=None,
                                price_list=price_list,
                            )
                        )
                    for tier in area.get("SpecialPriceQuantityAreas") or []:
                        qty = int(tier.get("Quantity") or 0)
                        tier_price = Decimal(str(tier.get("SpecialPrice") or 0))
                        if qty <= 0 or tier_price <= 0:
                            continue
                        rows.append(
                            ProductPromotion(
                                sku=row["ItemCode"],
                                price=tier_price,
                                discount_percent=Decimal(
                                    str(tier.get("Discountin") or discount or 0)
                                ),
                                valid_from=valid_from,
                                valid_to=valid_to,
                                tier_quantity=qty,
                                price_list=price_list,
                            )
                        )
            scanned += len(batch)
            last_code = batch[-1]["ItemCode"]
            logger.info("SpecialPrices escaneados: %s · promociones: %s", scanned, len(rows))
            if limit and scanned >= limit:
                break
            if len(batch) < PAGE_SIZE:
                break
            await asyncio.sleep(0.02)
    finally:
        await sap.close()

    await init_db()
    async with SessionLocal() as session:
        await session.execute(delete(ProductPromotion))
        session.add_all(rows)
        await session.commit()
    logger.info("Promociones sincronizadas: %s", len(rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza promociones SAP")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(sync(limit=args.limit))


if __name__ == "__main__":
    main()
