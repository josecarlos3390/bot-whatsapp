"""Adaptador para catálogo y carrito nativos de WhatsApp.

Con los flags apagados, el bot usa su catálogo/carrito propio. Cuando Meta
habilite el catálogo, se activan los flags y este módulo arma los mensajes y
convierte los pedidos nativos en carrito del bot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import ProductImage, CatalogItem, Contact
from . import cart as cart_service

logger = logging.getLogger(__name__)


@dataclass
class NativeOrderItem:
    sku: str
    quantity: int
    item_price: Decimal | None = None
    currency: str = "BOB"


@dataclass
class NativeOrder:
    catalog_id: str = ""
    text: str = ""
    items: list[NativeOrderItem] = field(default_factory=list)


def is_ready() -> bool:
    return bool(
        settings.wa_native_catalog_enabled
        and settings.wa_catalog_id
        and settings.wa_access_token
        and settings.wa_phone_number_id
    )


def cart_ready() -> bool:
    return is_ready() and settings.wa_native_cart_enabled


def parse_order(message: dict) -> NativeOrder:
    order = message.get("order") or {}
    items = []
    for raw in order.get("product_items") or []:
        sku = (raw.get("product_retailer_id") or "").strip().upper()
        try:
            quantity = int(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        if not sku or quantity <= 0:
            continue
        price = raw.get("item_price")
        items.append(
            NativeOrderItem(
                sku=sku,
                quantity=quantity,
                item_price=Decimal(str(price)) if price is not None else None,
                currency=raw.get("currency") or "BOB",
            )
        )
    return NativeOrder(
        catalog_id=order.get("catalog_id") or settings.wa_catalog_id,
        text=order.get("text") or "",
        items=items,
    )


def order_text(order: NativeOrder) -> str:
    if not order.items:
        return "Pedido de catálogo sin productos."
    lines = ", ".join(f"{item.sku} x{item.quantity}" for item in order.items)
    return f"Pedido de catálogo: {lines}"


async def add_order_to_cart(
    session: AsyncSession, contact: Contact, order: NativeOrder
) -> tuple[dict, list[str]]:
    cart = await cart_service.get_or_create_cart(session, contact.id)
    errors: list[str] = []
    for item in order.items:
        try:
            await cart_service.add_item(
                session, cart, item.sku, item.quantity
            )
        except Exception as exc:  # noqa: BLE001 - seguir con el resto
            errors.append(f"{item.sku}: {exc}")
    summary = await cart_service.summary(session, cart)
    return summary, errors


async def replace_order_in_cart(
    session: AsyncSession, contact: Contact, order: NativeOrder
) -> tuple[dict, list[str]]:
    """El carrito nativo reemplaza el carrito del bot al confirmar."""
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.clear(session, cart)
    return await add_order_to_cart(session, contact, order)


def cart_status() -> dict:
    return {
        "native_cart_ready": cart_ready(),
        "server_side_cart": False,
        "sync_mode": "replace_on_native_order",
        "note": (
            "El carrito nativo vive en WhatsApp; el bot no puede borrarlo ni "
            "editarlo desde el servidor. Solo sincroniza el pedido recibido."
        ),
    }


def summary_text(summary: dict, errors: list[str] | None = None) -> str:
    lines = ["Recibí tu pedido del catálogo:"]
    for line in summary.get("items", []):
        lines.append(
            f"- {line['name']} x{line['quantity']} — "
            f"Bs {Decimal(line['line_total']):,.2f}"
        )
    lines.append(f"Total: Bs {Decimal(summary['total']):,.2f}")
    if errors:
        lines.append("No pude agregar: " + "; ".join(errors))
    lines.append("¿Confirmas el pedido para generar el QR?")
    return "\n".join(lines)


async def catalog_feed(
    session: AsyncSession, limit: int | None = None
) -> tuple[list[dict], int]:
    """Genera filas para un feed CSV de Commerce Manager."""
    stmt = (
        select(CatalogItem)
        .where(CatalogItem.active.is_(True), CatalogItem.stock > 0)
        .order_by(CatalogItem.sku)
    )
    if limit:
        stmt = stmt.limit(limit)
    items = list((await session.scalars(stmt)).all())
    # La foto puede estar en la ficha o en la tabla de imágenes.
    skus = [item.sku for item in items]
    imagenes: dict[str, str] = {}
    if skus:
        filas_imagen = (
            await session.execute(
                select(ProductImage.sku, ProductImage.url).where(
                    ProductImage.sku.in_(skus),
                    ProductImage.approved.is_(True),
                )
            )
        ).all()
        for sku, url in filas_imagen:
            imagenes.setdefault(sku, url)
    rows: list[dict] = []
    skipped = 0
    for item in items:
        image = (
            item.image_url
            or imagenes.get(item.sku)
            or settings.meta_catalog_placeholder_image
        )
        if not image:
            skipped += 1
            continue
        base = (settings.meta_catalog_link_base or "").rstrip("/")
        rows.append(
            {
                "id": item.sku,
                "title": item.name[:200],
                "description": (item.description or item.name)[:5000],
                "availability": "in stock",
                "condition": "new",
                "price": f"{Decimal(item.price):.2f} {item.currency}",
                "link": f"{base}/{item.sku}" if base else "",
                "image_link": image,
                "brand": item.brand or "ROHO",
                "category": item.category or "",
            }
        )
    return rows, skipped
