"""Simulación de reglas sin crear conversaciones ni modificar datos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogItem, ProductPromotion
from . import catalog, rule_policy, rules_engine

ACCESSORY_PREFIXES = (
    "bolsa",
    "caja",
    "cesto",
    "panel",
    "soporte",
    "rack",
    "base",
    "cable",
    "funda",
    "protector",
    "organizador",
)


def _is_main_product(name: str | None) -> bool:
    folded = (name or "").strip().lower()
    return not any(folded.startswith(prefix) for prefix in ACCESSORY_PREFIXES)


def _money(value: Decimal | float | int | None) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


async def _promotions(
    session: AsyncSession, skus: list[str]
) -> dict[str, Decimal]:
    if not skus:
        return {}
    today = date.today()
    rows = (
        await session.scalars(
            select(ProductPromotion).where(
                ProductPromotion.sku.in_(skus),
                ProductPromotion.tier_quantity.is_(None),
                ProductPromotion.price > 0,
                or_(
                    ProductPromotion.valid_from.is_(None),
                    ProductPromotion.valid_from <= today,
                ),
                or_(
                    ProductPromotion.valid_to.is_(None),
                    ProductPromotion.valid_to >= today,
                ),
            )
        )
    ).all()
    result: dict[str, Decimal] = {}
    for row in rows:
        result[row.sku] = max(result.get(row.sku, Decimal("0")), row.price)
    return result


async def simulate(
    session: AsyncSession,
    *,
    query: str,
    area: str = "ecommerce",
    limit: int = 6,
) -> dict:
    query = (query or "").strip()
    if not query:
        return {
            "ok": False,
            "detail": "Escribí una consulta para simular.",
            "products": [],
            "rules": [],
        }

    items = await catalog.search_items(
        session, query, limit=limit, only_available=True
    )
    items = [item for item in items if _is_main_product(item.name)]
    promos = await _promotions(session, [item.sku for item in items])
    products: list[dict] = []
    for item in items:
        promos_price = promos.get(item.sku)
        current = promos_price if promos_price is not None else catalog.price_of(item)
        price = catalog.price_of(item)
        discount = 0.0
        if price > 0 and current < price:
            discount = round(float((price - current) / price * 100), 2)
        products.append(
            {
                "sku": item.sku,
                "name": item.name,
                "brand": item.brand,
                "category": item.category,
                "price": _money(price),
                "promo_price": _money(current),
                "promo_discount_percent": discount,
                "available": bool((item.stock or 0) > 0),
            }
        )

    matched = await rules_engine.rules_for(
        session, area=area, category=query, intent="search"
    )
    ordered = rules_engine.order_products(products, matched)
    ordered = rules_engine.order_promotions(
        ordered,
        [rule for rule in matched if rule.rule_type == "promotion_priority"],
    )
    # Texto exacto que el bot le pasa al modelo con estas reglas.
    policy = await rule_policy.build(
        session, query, intent="search"
    )
    prompt_text = policy.prompt_text()

    return {
        "ok": True,
        "query": query,
        "area": area,
        "products": ordered,
        "rules": [
            {
                "id": rule.id,
                "name": rule.name,
                "rule_type": rule.rule_type,
                "priority": rule.priority,
                "condition": rule.condition or {},
                "action": rule.action or {},
            }
            for rule in matched
        ],
        "prompt_text": prompt_text,
        "note": (
            "La simulación usa catálogo y reglas publicadas. "
            "No muestra cantidades de stock ni crea una conversación."
        ),
    }
