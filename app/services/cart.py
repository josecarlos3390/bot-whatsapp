from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Cart, CartItem
from . import catalog, pricing

logger = logging.getLogger(__name__)


class CartError(ValueError):
    pass


async def _offer(session: AsyncSession, sku: str, quantity: int):
    return await pricing.get_offer(session, sku, quantity)


def _store_name(code: str) -> str:
    return settings.sap_store_map.get(code, code)


def _choose_store(offer, quantity: int, preferred: str | None = None) -> str | None:
    stock = offer.stock_by_store or {}
    if preferred and stock.get(preferred, 0) >= quantity:
        return preferred
    candidates = [
        (code, stock.get(code, 0)) for code in settings.sap_store_map
    ]
    enough = [(code, qty) for code, qty in candidates if qty >= quantity]
    if enough:
        return max(enough, key=lambda pair: pair[1])[0]
    if stock:
        return max(stock.items(), key=lambda pair: pair[1])[0]
    return None


def _stock_error(offer, quantity: int) -> str:
    details = ", ".join(
        f"{_store_name(code)}: {offer.stock_by_store.get(code, 0)}"
        for code in settings.sap_store_map
    )
    return (
        f"No hay {quantity} unidades de {offer.name} en una sola tienda. "
        f"Disponible por tienda: {details}."
    )


async def get_or_create_cart(session: AsyncSession, contact_id: str) -> Cart:
    cart = await session.scalar(
        select(Cart)
        .where(Cart.contact_id == contact_id, Cart.status == "active")
        .order_by(Cart.created_at.desc())
    )
    if cart is not None:
        return cart
    cart = Cart(contact_id=contact_id, status="active")
    session.add(cart)
    await session.commit()
    return cart


async def items(session: AsyncSession, cart: Cart) -> list[CartItem]:
    return list(
        (
            await session.scalars(
                select(CartItem)
                .where(CartItem.cart_id == cart.id)
                .order_by(CartItem.sku)
            )
        ).all()
    )


async def add_item(
    session: AsyncSession,
    cart: Cart,
    sku: str,
    quantity: int = 1,
    store_code: str | None = None,
) -> Cart:
    if quantity <= 0:
        raise CartError("La cantidad debe ser mayor a cero.")
    existing = await session.scalar(
        select(CartItem).where(
            CartItem.cart_id == cart.id, CartItem.sku == sku.strip().upper()
        )
    )
    new_quantity = quantity + (existing.quantity if existing else 0)
    offer = await _offer(session, sku, new_quantity)
    if offer is None:
        raise CartError(f"No encontré el producto {sku}.")

    if store_code:
        store = store_code
        if offer.stock_by_store.get(store, 0) < new_quantity:
            raise CartError(_stock_error(offer, new_quantity))
    else:
        store = _choose_store(
            offer, new_quantity, existing.store_code if existing else None
        )
        if store is None or offer.stock_by_store.get(store, 0) < new_quantity:
            raise CartError(_stock_error(offer, new_quantity))

    if existing is None:
        session.add(
            CartItem(
                cart_id=cart.id,
                sku=offer.sku,
                quantity=new_quantity,
                unit_price=offer.final_price,
                list_price=offer.base_price,
                discount_percent=offer.discount_percent,
                store_code=store,
            )
        )
    else:
        existing.quantity = new_quantity
        existing.unit_price = offer.final_price
        existing.list_price = offer.base_price
        existing.discount_percent = offer.discount_percent
        existing.store_code = store

    await session.commit()
    return cart


async def set_quantity(
    session: AsyncSession, cart: Cart, sku: str, quantity: int
) -> Cart:
    if quantity <= 0:
        return await remove_item(session, cart, sku)
    existing = await session.scalar(
        select(CartItem).where(
            CartItem.cart_id == cart.id, CartItem.sku == sku.strip().upper()
        )
    )
    if existing is None:
        raise CartError(f"El producto {sku} no está en el carrito.")

    offer = await _offer(session, sku, quantity)
    if offer is None:
        raise CartError(f"No encontré el producto {sku}.")
    store = _choose_store(offer, quantity, existing.store_code)
    if store is None or offer.stock_by_store.get(store, 0) < quantity:
        raise CartError(_stock_error(offer, quantity))

    existing.quantity = quantity
    existing.unit_price = offer.final_price
    existing.list_price = offer.base_price
    existing.discount_percent = offer.discount_percent
    existing.store_code = store
    await session.commit()
    return cart


async def remove_item(session: AsyncSession, cart: Cart, sku: str) -> Cart:
    await session.execute(
        delete(CartItem).where(CartItem.cart_id == cart.id, CartItem.sku == sku)
    )
    await session.commit()
    return cart


async def clear(session: AsyncSession, cart: Cart) -> Cart:
    await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    await session.commit()
    return cart


async def summary(session: AsyncSession, cart: Cart) -> dict:
    rows = await items(session, cart)
    lines = []
    subtotal = Decimal("0")
    for line in rows:
        product = await catalog.get_item(session, line.sku)
        name = product.name if product else line.sku
        line_total = Decimal(line.unit_price) * line.quantity
        subtotal += line_total
        lines.append(
            {
                "sku": line.sku,
                "name": name,
                "quantity": line.quantity,
                "unit_price": Decimal(line.unit_price),
                "list_price": Decimal(line.list_price or line.unit_price),
                "discount_percent": Decimal(line.discount_percent or 0),
                "store_code": line.store_code,
                "store_name": _store_name(line.store_code) if line.store_code else None,
                "line_total": line_total,
            }
        )
    return {
        "items": lines,
        "count": sum(line.quantity for line in rows),
        "subtotal": subtotal,
        "total": subtotal,
        "currency": cart.currency,
    }
