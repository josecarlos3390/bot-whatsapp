"""Memoria de recomendaciones para justificarlas con datos reales."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, ConversationRecommendation


def _money(value) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "0")


async def save(
    session: AsyncSession,
    contact_id: str,
    *,
    query: str | None,
    category: str | None,
    brand: str | None,
    size: str | None,
    min_price: float | None,
    max_price: float | None,
    products: list[dict],
) -> None:
    if not products:
        return
    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact_id)
    )
    if conversation is None:
        return
    snapshot = [
        {
            "sku": product.get("sku"),
            "name": product.get("name"),
            "brand": product.get("brand"),
            "category": product.get("category"),
            "description": (product.get("description") or "")[:300],
            "price": product.get("price"),
            "promo_price": product.get("promo_price"),
            "promo_discount_percent": product.get("promo_discount_percent"),
            "stock": product.get("stock"),
        }
        for product in products[:8]
    ]
    session.add(
        ConversationRecommendation(
            conversation_id=conversation.id,
            query=query,
            category=category,
            brand=brand,
            size=size,
            min_price=min_price,
            max_price=max_price,
            products=snapshot,
        )
    )
    await session.commit()


async def latest(
    session: AsyncSession, contact_id: str
) -> ConversationRecommendation | None:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact_id)
    )
    if conversation is None:
        return None
    return await session.scalar(
        select(ConversationRecommendation)
        .where(
            ConversationRecommendation.conversation_id == conversation.id
        )
        .order_by(ConversationRecommendation.created_at.desc())
        .limit(1)
    )


def explain(snapshot: ConversationRecommendation) -> str:
    products = snapshot.products or []
    if not products:
        return ""
    query = snapshot.query or snapshot.category or "tu búsqueda"
    if query.strip().lower() == "tv":
        query = "televisores"
    criteria: list[str] = []
    if snapshot.category:
        criteria.append(f"categoría {snapshot.category}")
    if snapshot.brand:
        criteria.append(f"marca {snapshot.brand}")
    if snapshot.size:
        criteria.append(f"medida {snapshot.size}")
    if snapshot.min_price is not None or snapshot.max_price is not None:
        if snapshot.max_price is not None:
            criteria.append(f"presupuesto hasta Bs {_money(snapshot.max_price)}")
        if snapshot.min_price is not None:
            criteria.append(f"desde Bs {_money(snapshot.min_price)}")
    criteria.append("precio")
    criteria.append("disponibilidad")
    with_promo = [
        product
        for product in products
        if product.get("promo_discount_percent")
    ]
    if with_promo:
        criteria.append("promoción vigente")
    else:
        criteria.append("sin promoción vigente")

    lines = [
        f"Te recomendé {len(products)} opción(es) para *{query}* "
        f"porque cumplían: {', '.join(criteria)}."
    ]
    for index, product in enumerate(products[:4], start=1):
        name = product.get("name") or "Producto"
        price = product.get("promo_price") or product.get("price")
        line = f"{index}. {name} — Bs {_money(price)}"
        if product.get("promo_discount_percent"):
            line += f" ({product['promo_discount_percent']}% de descuento)"
        else:
            line += " (precio normal)"
        if product.get("brand"):
            line += f" · {product['brand']}"
        lines.append(line)
    prices = [
        (product.get("promo_price") or product.get("price"), product)
        for product in products
    ]
    try:
        cheapest_price, cheapest = min(
            prices,
            key=lambda item: Decimal(str(item[0] or "0")),
        )
    except (InvalidOperation, TypeError, ValueError):
        cheapest_price, cheapest = None, None
    if cheapest is not None:
        lines.append(
            f"La más económica es *{cheapest.get('name')}* "
            f"a Bs {_money(cheapest_price)}."
        )
    if with_promo:
        best = max(
            with_promo,
            key=lambda product: Decimal(
                str(product.get("promo_discount_percent") or "0")
            ),
        )
        lines.append(
            f"La de mayor descuento es *{best.get('name')}* "
            f"({best.get('promo_discount_percent')}%)."
        )
    if with_promo:
        lines.append(
            "El descuento es el que estaba vigente en el catálogo; no lo "
            "inventé ni prometí un precio futuro."
        )
    else:
        lines.append(
            "No había una promoción vigente en esa búsqueda: el criterio fue "
            "coincidencia, disponibilidad y precio, no un descuento."
        )
    lines.append(
        "No uso una medida de “calidad” que no esté en el catálogo: "
        "me baso en marca, medida, características y precio."
    )
    lines.append(
        "No mostré paneles, racks ni soportes como televisores."
        if query == "televisores"
        else "Si querés, puedo ordenarlas por precio, medida o marca."
    )
    return "\n".join(lines)
