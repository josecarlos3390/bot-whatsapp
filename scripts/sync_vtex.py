"""Repuebla el catálogo local del bot desde PaasVTEX (solo lectura).

Uso:
    python -m scripts.sync_vtex
    python -m scripts.sync_vtex --deactivate-missing
    python -m scripts.sync_vtex --promotions --promotions-limit 200

Requiere SAP_MODE=vtex y un PaasVTEX con /api/vtex/items/export.
No habla con VTEX directamente: las credenciales viven en el PaaS.
No toca las compras ni crea pedidos.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import re
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select, update

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import CatalogItem, ProductImage, ProductPromotion
from app.sap import SapError, get_sap

logger = logging.getLogger("sync_vtex")
PAGE_SIZE = 50
PAGE_DELAY_SECONDS = 0.25
PRICE_RANGES = [
    "[0 TO 100]",
    "[100 TO 500]",
    "[500 TO 1000]",
    "[1000 TO 5000]",
    "[5000 TO 10000]",
    "[10000 TO 50000]",
    "[50000 TO 1000000]",
    "[1000000 TO 100000000]",
]


def _clean(value: str | None, limit: int | None = None) -> str | None:
    if not value:
        return None
    text = str(value).strip().strip('"').strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _barcode(value: str | None) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits or None


_TAG_RE = re.compile(r"<[^>]+>")


def _plain(value: str | None, limit: int | None = None) -> str | None:
    """Quita HTML de la descripción de VTEX: el cliente la lee en el chat."""
    text = _clean(value)
    if not text:
        return None
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _keywords(row: dict) -> str | None:
    parts = [
        row.get("sku"),
        row.get("name"),
        row.get("brand"),
        row.get("category"),
        row.get("barcode"),
    ]
    text = " ".join(str(part) for part in parts if part)
    return text[:4000] or None


def _catalog_fields(row: dict) -> dict:
    category = _clean(row.get("category"), 80)
    attributes = (
        dict(row.get("attributes"))
        if isinstance(row.get("attributes"), dict)
        else {"source": "vtex"}
    )
    current_price = Decimal(str(row.get("price") or 0))
    try:
        list_price = Decimal(str(attributes.get("list_price") or 0))
    except Exception:  # noqa: BLE001
        list_price = Decimal("0")
    base_price = list_price if list_price > current_price else current_price
    attributes["vtex_current_price"] = str(current_price)
    if list_price > 0:
        attributes["vtex_list_price"] = str(list_price)
    return {
        "name": _clean(row.get("name"), 200) or _clean(row.get("sku"), 64) or "?",
        "foreign_name": None,
        "description": _plain(row.get("description"), 1000),
        "category": category,
        "group_code": None,
        "group_name": category,
        "brand": _clean(row.get("brand"), 80),
        "manufacturer_code": None,
        "barcode": _barcode(row.get("barcode")),
        "attributes": attributes,
        "sales_unit": "UN",
        "price": base_price,
        "currency": _clean(row.get("currency"), 3) or "BOB",
        "stock": int(row.get("stock") or 0),
        "image_url": _clean(row.get("image_url"), 500),
        "keywords": _keywords(row),
        "active": True,
        "sap_valid": True,
        "sap_updated_at": None,
        "synced_at": datetime.now(timezone.utc),
    }


async def _upsert_item(session, row: dict) -> bool:
    sku = _clean(row.get("sku"), 64)
    if not sku:
        return False

    values = _catalog_fields(row)
    existing = await session.scalar(
        select(CatalogItem).where(CatalogItem.sku == sku)
    )
    if existing is None:
        session.add(CatalogItem(sku=sku, **values))
        created = True
    else:
        for key, value in values.items():
            setattr(existing, key, value)
        created = False

    image_url = values.get("image_url")
    if image_url:
        image = await session.scalar(
            select(ProductImage).where(
                ProductImage.sku == sku,
                ProductImage.url == image_url,
            )
        )
        if image is None:
            session.add(
                ProductImage(
                    sku=sku,
                    url=image_url,
                    alt=values["name"],
                    position=1,
                    source="vtex",
                    is_primary=True,
                    approved=True,
                )
            )
        else:
            image.is_primary = True
            image.approved = True
            image.source = "vtex"

    return created


async def _sync_promotions(session, skus: list[str], max_skus: int) -> int:
    await session.execute(delete(ProductPromotion))
    rows_added = 0
    selected = skus[:max_skus] if max_skus > 0 else skus
    sap = get_sap(session)
    try:
        for index, sku in enumerate(selected, start=1):
            try:
                periods = await sap.get_price_periods(sku)
            except Exception:  # noqa: BLE001
                logger.exception("No se pudieron leer precios VTEX de %s", sku)
                continue

            for period in periods:
                if period.price is not None and period.price > 0:
                    session.add(
                        ProductPromotion(
                            sku=sku,
                            price=period.price,
                            discount_percent=period.discount_percent,
                            valid_from=period.valid_from,
                            valid_to=period.valid_to,
                            tier_quantity=None,
                            price_list=period.price_list,
                            source="vtex_fixed_price",
                            synced_at=datetime.now(timezone.utc),
                        )
                    )
                    rows_added += 1

                for tier in period.tiers:
                    if tier.price <= 0:
                        continue
                    session.add(
                        ProductPromotion(
                            sku=sku,
                            price=tier.price,
                            discount_percent=tier.discount_percent,
                            valid_from=period.valid_from,
                            valid_to=period.valid_to,
                            tier_quantity=tier.quantity,
                            price_list=period.price_list,
                            source="vtex_fixed_price",
                            synced_at=datetime.now(timezone.utc),
                        )
                    )
                    rows_added += 1

            if index % 25 == 0:
                await session.commit()
                logger.info("Precios VTEX: %s/%s SKU", index, len(selected))

        await session.commit()
    finally:
        await sap.close()

    return rows_added


async def _export_page(
    sap, offset: int, brand_id: str | None, price_range: str | None = None
) -> list[dict]:
    for attempt in range(8):
        try:
            return await sap.export_items(
                str(offset),
                PAGE_SIZE,
                brand_id=brand_id,
                price_range=price_range,
            )
        except SapError as exc:
            transient = any(
                code in str(exc)
                for code in ("429", "500", "502", "503", "504")
            )
            if not transient or attempt == 7:
                raise
            delay = min(2**attempt, 60)
            logger.warning(
                "Export VTEX falló (%s); reintento %s/7 en %ss",
                exc,
                attempt + 1,
                delay,
            )
            await asyncio.sleep(delay)
    return []


async def sync(
    limit: int | None = None,
    deactivate_missing: bool = False,
    promotions: bool = False,
    promotions_limit: int = 200,
    dry_run: bool = False,
) -> None:
    if settings.sap_mode != "vtex":
        raise SystemExit(
            "SAP_MODE debe ser 'vtex' para sincronizar el catálogo desde PaasVTEX"
        )

    started_at = datetime.now(timezone.utc)
    await init_db()

    created = 0
    updated = 0
    seen: list[str] = []
    offset = 0

    async with SessionLocal() as session:
        sap = get_sap(session)
        try:
            try:
                brands = await sap.get_brands()
            except Exception:  # noqa: BLE001
                logger.exception("No se pudieron leer las marcas VTEX")
                brands = []

            brand_ids: list[str | None] = [
                str(row.get("id"))
                for row in brands
                if row.get("id") not in (None, "")
            ]
            if not brand_ids:
                brand_ids = [None]
            logger.info("Marcas VTEX a recorrer: %s", len(brand_ids))

            async def consume(page: list[dict]) -> None:
                nonlocal created, updated
                for row in page:
                    if limit and len(seen) >= limit:
                        break

                    sku = _clean(row.get("sku"), 64)
                    if not sku:
                        continue

                    if dry_run:
                        created += 1
                    else:
                        was_created = await _upsert_item(session, row)
                        if was_created:
                            created += 1
                        else:
                            updated += 1
                    seen.append(sku)

            for brand_id in brand_ids:
                offset = 0
                capped = False
                while True:
                    page = await _export_page(sap, offset, brand_id)
                    if not page:
                        break

                    await consume(page)

                    if not dry_run:
                        await session.commit()

                    logger.info(
                        "Catálogo VTEX: %s vistos · marca %s offset %s",
                        len(seen),
                        brand_id,
                        offset,
                    )

                    if limit and len(seen) >= limit:
                        break

                    offset += PAGE_SIZE
                    await asyncio.sleep(PAGE_DELAY_SECONDS)
                    if len(page) < PAGE_SIZE:
                        break
                    if offset >= 2500:
                        capped = True
                        logger.warning(
                            "Marca %s alcanzó el límite de 2.500; "
                            "se reparte por rango de precio",
                            brand_id,
                        )
                        break

                if limit and len(seen) >= limit:
                    break

                if not capped:
                    continue

                for price_range in PRICE_RANGES:
                    offset = 0
                    while True:
                        page = await _export_page(
                            sap, offset, brand_id, price_range
                        )
                        if not page:
                            break

                        await consume(page)

                        if not dry_run:
                            await session.commit()

                        logger.info(
                            "Catálogo VTEX: %s vistos · marca %s · %s offset %s",
                            len(seen),
                            brand_id,
                            price_range,
                            offset,
                        )

                        if limit and len(seen) >= limit:
                            break

                        offset += PAGE_SIZE
                        await asyncio.sleep(PAGE_DELAY_SECONDS)
                        if len(page) < PAGE_SIZE:
                            break
                        if offset >= 2500:
                            logger.warning(
                                "Marca %s rango %s alcanzó 2.500; "
                                "puede faltar catálogo",
                                brand_id,
                                price_range,
                            )
                            break

                    if limit and len(seen) >= limit:
                        break

                if limit and len(seen) >= limit:
                    break

            logger.info(
                "Catálogo VTEX: %s nuevos, %s actualizados, %s vistos",
                created, updated, len(seen),
            )

            if promotions and not dry_run:
                promo_count = await _sync_promotions(
                    session, seen, promotions_limit
                )
                logger.info("Promociones VTEX: %s filas", promo_count)

            if deactivate_missing:
                if limit:
                    logger.warning(
                        "Se ignoró --deactivate-missing porque se usó --limit"
                    )
                elif not dry_run:
                    result = await session.execute(
                        update(CatalogItem)
                        .where(CatalogItem.synced_at < started_at)
                        .values(active=False)
                    )
                    await session.commit()
                    logger.info(
                        "Artículos desactivados por no venir de VTEX: %s",
                        result.rowcount,
                    )
        finally:
            await sap.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sincroniza el catálogo del bot desde PaasVTEX"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Desactiva artículos que ya no vienen de VTEX",
    )
    parser.add_argument(
        "--promotions",
        action="store_true",
        help="Reemplaza promociones locales con precios fijos de VTEX",
    )
    parser.add_argument(
        "--promotions-limit",
        type=int,
        default=200,
        help="Máximo de SKU a consultar para promociones (0 = todos)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(
        sync(
            limit=args.limit,
            deactivate_missing=args.deactivate_missing,
            promotions=args.promotions,
            promotions_limit=args.promotions_limit,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
