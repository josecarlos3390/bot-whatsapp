"""Sincroniza artículos de SAP Business One al catálogo local.

Uso:
    python -m scripts.sync_catalog --limit 100
    python -m scripts.sync_catalog --deactivate-missing

El catálogo local es el que usa el bot para buscar; SAP sigue siendo la fuente
de verdad para precio/stock al momento de crear el pedido.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import CatalogItem
from app.sap import ServiceLayerSap

logger = logging.getLogger("sync_catalog")

FILTER = "Valid eq 'tYES' and SalesItem eq 'tYES' and ItemType eq 'itItems'"
SELECT = (
    "ItemCode,ItemName,ForeignName,User_Text,SalesUnit,ItemsGroupCode,"
    "QuantityOnStock,Valid,SalesItem,Manufacturer,U_FAMILIA,U_LINEA,"
    "U_SC_Sinonimo,UpdateDate,UpdateTime,ItemPrices"
)
PAGE_SIZE = 20  # SAP Service Layer devuelve como máximo 20 por página.


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).strip().strip('"').strip() or None


def _updated_at(item: dict) -> datetime | None:
    raw_date = item.get("UpdateDate")
    if not raw_date:
        return None
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    raw_time = item.get("UpdateTime")
    if raw_time:
        try:
            hour, minute, second = (int(part) for part in raw_time.split(":")[:3])
            parsed = parsed.replace(hour=hour, minute=minute, second=second)
        except (ValueError, TypeError):
            pass
    return parsed


def _price(item: dict) -> Decimal | None:
    prices = item.get("ItemPrices") or []
    if not prices:
        return None
    chosen = next(
        (p for p in prices if p.get("PriceList") == settings.sap_price_list),
        prices[0],
    )
    try:
        value = Decimal(str(chosen.get("Price", 0)))
    except Exception:  # noqa: BLE001
        return None
    return value if value > 0 else None


async def _fetch_all(
    sap: ServiceLayerSap,
    path: str,
    select_fields: str,
    order_by: str | None = None,
    max_rows: int | None = None,
    filter_expr: str | None = None,
    keyset_field: str | None = None,
) -> list[dict]:
    rows: list[dict] = []
    skip = 0
    last_key: str | None = None
    while True:
        params: dict = {"$top": PAGE_SIZE, "$select": select_fields}
        if order_by:
            params["$orderby"] = order_by
        expr = filter_expr
        if keyset_field and last_key is not None:
            escaped = last_key.replace("'", "''")
            condition = f"{keyset_field} gt '{escaped}'"
            expr = f"({filter_expr}) and {condition}" if filter_expr else condition
        if expr:
            params["$filter"] = expr
        if not keyset_field:
            params["$skip"] = skip
        data = await sap.get(path, params=params)
        batch = data.get("value", [])
        if not batch:
            break
        rows.extend(batch)
        logger.info("%s: %s filas", path, len(rows))
        if max_rows and len(rows) >= max_rows:
            rows = rows[:max_rows]
            break
        if len(batch) < PAGE_SIZE:
            break
        if keyset_field:
            last_key = str(batch[-1][keyset_field])
        else:
            skip += PAGE_SIZE
        await asyncio.sleep(0.02)
    return rows


async def sync(limit: int | None = None, deactivate_missing: bool = False) -> None:
    started_at = datetime.now(timezone.utc)
    sap = ServiceLayerSap(session=None)  # type: ignore[arg-type]
    try:
        logger.info("Cargando grupos y fabricantes...")
        groups = await _fetch_all(sap, "ItemGroups", "Number,GroupName")
        manufacturers = await _fetch_all(
            sap, "Manufacturers", "Code,ManufacturerName"
        )
        group_names = {
            row["Number"]: row.get("GroupName") for row in groups if "Number" in row
        }
        manufacturer_names = {
            row["Code"]: row.get("ManufacturerName")
            for row in manufacturers
            if "Code" in row
        }
        logger.info(
            "Grupos: %s · fabricantes: %s", len(group_names), len(manufacturer_names)
        )

        logger.info("Descargando artículos vendibles...")
        items = await _fetch_all(
            sap,
            "Items",
            SELECT,
            order_by="ItemCode",
            max_rows=limit,
            filter_expr=FILTER,
            keyset_field="ItemCode",
        )
        logger.info("Artículos descargados: %s", len(items))
    finally:
        await sap.close()

    if not items:
        logger.warning("SAP no devolvió artículos; no se toca el catálogo")
        return

    await init_db()
    async with SessionLocal() as session:
        existing = {
            row.sku: row
            for row in (await session.scalars(select(CatalogItem))).all()
        }
        added = updated = skipped = 0
        synced_at = datetime.now(timezone.utc)

        for index, item in enumerate(items, start=1):
            sku = item.get("ItemCode")
            name = _clean(item.get("ItemName"))
            price = _price(item)
            if not sku or not name or price is None:
                skipped += 1
                continue

            foreign_name = _clean(item.get("ForeignName"))
            description = _clean(item.get("User_Text")) or foreign_name or name
            group_code = item.get("ItemsGroupCode")
            manufacturer_code = item.get("Manufacturer")
            keywords = " ".join(
                filter(
                    None,
                    [
                        name,
                        foreign_name,
                        _clean(item.get("U_FAMILIA")),
                        _clean(item.get("U_LINEA")),
                        _clean(item.get("U_SC_Sinonimo")),
                        group_names.get(group_code),
                        manufacturer_names.get(manufacturer_code),
                    ],
                )
            )

            values = {
                "name": name[:200],
                "foreign_name": (foreign_name or None) and foreign_name[:200],
                "description": description,
                "category": (group_names.get(group_code) or None)
                and group_names[group_code][:80],
                "group_code": group_code,
                "group_name": (group_names.get(group_code) or None)
                and group_names[group_code][:80],
                "brand": (manufacturer_names.get(manufacturer_code) or None)
                and manufacturer_names[manufacturer_code][:80],
                "manufacturer_code": manufacturer_code,
                "sales_unit": _clean(item.get("SalesUnit")),
                "price": price,
                "currency": "BOB",
                "stock": int(item.get("QuantityOnStock") or 0),
                "keywords": keywords,
                "active": True,
                "sap_valid": item.get("Valid") == "tYES",
                "sap_updated_at": _updated_at(item),
                "synced_at": synced_at,
            }

            row = existing.get(sku)
            if row is None:
                session.add(CatalogItem(sku=sku, **values))
                added += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1

            if index % 500 == 0:
                await session.commit()
                logger.info(
                    "Progreso %s/%s (nuevos %s, actualizados %s)",
                    index,
                    len(items),
                    added,
                    updated,
                )

        if deactivate_missing:
            await session.execute(
                update(CatalogItem)
                .where(CatalogItem.synced_at < started_at)
                .values(active=False)
            )

        await session.commit()
        logger.info(
            "Listo: %s nuevos, %s actualizados, %s omitidos",
            added,
            updated,
            skipped,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza catálogo SAP B1")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de artículos")
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Desactiva artículos que ya no vinieron en esta sincronización",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(sync(limit=args.limit, deactivate_missing=args.deactivate_missing))


if __name__ == "__main__":
    main()
