"""Refresco puntual de un SKU desde VTEX (precio, ficha y promociones)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CatalogItem, ProductImage, ProductPromotion
from ..sap import SapError, get_sap

logger = logging.getLogger(__name__)


def _discount(base: Decimal, current: Decimal) -> Decimal:
    if base <= 0 or current <= 0:
        return Decimal("0")
    return ((base - current) / base * 100).quantize(Decimal("0.01"))


async def refresh_item(session: AsyncSession, sku: str) -> dict:
    """Actualiza un SKU local con los datos actuales de VTEX.

    No recorre el catálogo: sirve para reflejar un cambio de precio/promoción
    inmediatamente después de editarlo en VTEX.
    """
    term = (sku or "").strip()
    if not term:
        return {"ok": False, "error": "Falta el SKU"}
    if settings.sap_mode != "vtex":
        return {
            "ok": False,
            "error": "El refresco puntual solo está disponible con SAP_MODE=vtex",
        }

    row = await session.scalar(
        select(CatalogItem).where(CatalogItem.sku == term)
    )
    if row is None:
        row = await session.scalar(
            select(CatalogItem).where(
                func.lower(CatalogItem.sku) == term.lower()
            )
        )
    if row is None:
        return {
            "ok": False,
            "error": "El SKU no existe en el catálogo local; ejecutá el sync completo",
        }

    sap = get_sap(session)
    try:
        item = await sap.get_item(term, force_refresh=True)
        if item is None:
            return {"ok": False, "error": "SKU no encontrado en VTEX"}

        periods = []
        try:
            periods = await sap.get_price_periods(term, force_refresh=True)
        except SapError:
            logger.exception("No se pudieron leer los períodos de %s", term)

        current_price = Decimal(item.price)
        list_price = Decimal(item.list_price or 0)
        base_price = list_price if list_price > current_price else current_price

        today = date.today()
        active = [
            period
            for period in periods
            if (period.valid_from is None or period.valid_from <= today)
            and (period.valid_to is None or today <= period.valid_to)
        ]
        period = (
            max(active, key=lambda p: p.valid_from or date.min)
            if active
            else None
        )

        attributes = dict(row.attributes or {})
        attributes["source"] = "vtex"
        attributes["vtex_current_price"] = str(current_price)
        if list_price > 0:
            attributes["vtex_list_price"] = str(list_price)
        if period is not None and period.valid_to is not None:
            attributes["price_valid_until"] = period.valid_to.isoformat()

        row.name = (item.name or row.name)[:200]
        row.description = item.description or row.description
        row.brand = item.brand or row.brand
        row.category = item.category or row.category
        row.barcode = item.barcode or row.barcode
        row.image_url = item.image_url or row.image_url
        row.price = base_price
        row.currency = item.currency or row.currency or "BOB"
        row.stock = int(item.stock or 0)
        row.attributes = attributes
        row.active = True
        row.synced_at = datetime.now(timezone.utc)

        if item.image_url:
            image = await session.scalar(
                select(ProductImage).where(
                    ProductImage.sku == row.sku,
                    ProductImage.url == item.image_url,
                )
            )
            if image is None:
                session.add(
                    ProductImage(
                        sku=row.sku,
                        url=item.image_url,
                        alt=row.name,
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

        await session.execute(
            delete(ProductPromotion).where(
                ProductPromotion.sku == row.sku,
                ProductPromotion.source.in_(
                    ["vtex_catalog", "vtex_fixed_price"]
                ),
            )
        )

        discount = Decimal("0")
        if base_price > current_price and current_price > 0:
            discount = _discount(base_price, current_price)
            session.add(
                ProductPromotion(
                    sku=row.sku,
                    price=current_price,
                    discount_percent=discount,
                    valid_from=period.valid_from if period else None,
                    valid_to=period.valid_to if period else None,
                    tier_quantity=None,
                    price_list=1,
                    source="vtex_catalog",
                    synced_at=datetime.now(timezone.utc),
                )
            )
            if period is not None:
                for tier in period.tiers:
                    if tier.price <= 0:
                        continue
                    session.add(
                        ProductPromotion(
                            sku=row.sku,
                            price=tier.price,
                            discount_percent=_discount(base_price, tier.price),
                            valid_from=period.valid_from,
                            valid_to=period.valid_to,
                            tier_quantity=tier.quantity,
                            price_list=1,
                            source="vtex_fixed_price",
                            synced_at=datetime.now(timezone.utc),
                        )
                    )

        await session.commit()
        logger.info(
            "SKU %s refrescado desde VTEX: base %s, actual %s, descuento %s",
            row.sku,
            base_price,
            current_price,
            discount,
        )
        return {
            "ok": True,
            "sku": row.sku,
            "name": row.name,
            "price": str(base_price),
            "current_price": str(current_price),
            "list_price": str(list_price) if list_price > 0 else None,
            "discount_percent": str(discount),
            "stock": row.stock,
            "currency": row.currency,
            "valid_from": period.valid_from.isoformat() if period and period.valid_from else None,
            "valid_to": period.valid_to.isoformat() if period and period.valid_to else None,
            "source": "vtex",
        }
    finally:
        await sap.close()
