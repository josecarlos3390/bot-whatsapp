"""Single price resolver: SAP first, local promotions as safe fallback."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CatalogItem, ProductPromotion
from ..sap import (
    PricePeriod,
    QuantityTier,
    SapAdapter,
    SapItem,
    build_offer,
    get_sap,
)
from . import catalog

logger = logging.getLogger(__name__)


def _promotions_to_periods(rows: list[ProductPromotion]) -> list[PricePeriod]:
    grouped: dict[tuple[date | None, date | None], dict] = {}
    for row in rows:
        key = (row.valid_from, row.valid_to)
        group = grouped.setdefault(key, {"price": None, "tiers": []})
        if row.tier_quantity is None:
            if row.price > 0:
                group["price"] = (
                    row.price
                    if group["price"] is None
                    else min(group["price"], row.price)
                )
        elif row.tier_quantity > 0 and row.price > 0:
            group["tiers"].append(
                QuantityTier(
                    quantity=row.tier_quantity,
                    price=row.price,
                    discount_percent=row.discount_percent,
                )
            )
    periods = []
    for (valid_from, valid_to), group in grouped.items():
        periods.append(
            PricePeriod(
                valid_from=valid_from,
                valid_to=valid_to,
                price=group["price"],
                price_list=settings.sap_price_list,
                tiers=sorted(group["tiers"], key=lambda tier: tier.quantity),
            )
        )
    return periods


async def local_offer(
    session: AsyncSession, sku: str, quantity: int = 1
):
    item = await catalog.get_item(session, sku)
    if item is None:
        return None
    today = date.today()
    rows = list(
        (
            await session.scalars(
                select(ProductPromotion).where(
                    ProductPromotion.sku == sku.strip().upper(),
                    ProductPromotion.price_list == settings.sap_price_list,
                    (
                        ProductPromotion.valid_from.is_(None)
                        | (ProductPromotion.valid_from <= today)
                    ),
                    (
                        ProductPromotion.valid_to.is_(None)
                        | (ProductPromotion.valid_to >= today)
                    ),
                )
            )
        ).all()
    )
    sap_item = SapItem(
        sku=item.sku,
        name=item.name,
        price=Decimal(item.price),
        stock=item.stock,
        currency=item.currency,
        stock_by_store={settings.sap_warehouse: item.stock},
    )
    return build_offer(sap_item, _promotions_to_periods(rows), quantity)


async def get_offer(
    session: AsyncSession,
    sku: str,
    quantity: int = 1,
    *,
    force_refresh: bool = False,
    sap: SapAdapter | None = None,
):
    """SAP is authoritative; local promos are used only on read fallback.

    Checkout passes force_refresh=True and must fail if SAP is unavailable.
    """
    adapter = sap or get_sap(session)
    # HybridSap already falls back to the local base item when SAP is down,
    # losing local promotions. For pricing, hit its live reader directly and
    # let this service apply the local promotion fallback.
    live_adapter = (
        adapter
        if sap is not None
        else getattr(adapter, "reader", adapter)
    )
    try:
        offer = await live_adapter.get_offer(
            sku, quantity, force_refresh=force_refresh
        )
    except Exception:
        if force_refresh:
            raise
        logger.exception("SAP no disponible para %s; se usa catálogo local", sku)
        return await local_offer(session, sku, quantity)
    if offer is not None:
        return offer
    if force_refresh:
        return None
    return await local_offer(session, sku, quantity)
