"""Validación de salida: la última barrera antes de enviar al cliente.

No reemplaza al modelo ni a las reglas: los audita. Si algo se escapa (una
frase pobre, un producto que nadie pidió en un tema delicado, una referencia a
un SKU que no existe), se corrige acá.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import persona
from ..models import CatalogItem
from . import intent, policy

logger = logging.getLogger(__name__)

# Frases que no deben salir nunca.
BANNED: tuple[tuple[str, str], ...] = (
    (
        "no tengo una sección específica",
        "No tengo esa categoría armada, pero decime qué buscás y lo reviso.",
    ),
    (
        "no pude completar la consulta",
        "Se me complicó la consulta. ¿Me la repetís o te paso con un asesor?",
    ),
)

BANNED_PHRASES = tuple(phrase for phrase, _ in BANNED)

_ID_RE = re.compile(r"^(product|add):([^:]+)")


def _sku_from_id(value: str | None) -> str | None:
    match = _ID_RE.match(str(value or ""))
    return match.group(2).strip().upper() if match else None


async def _known_skus(session: AsyncSession, skus: set[str]) -> set[str]:
    if not skus:
        return set()
    rows = await session.scalars(
        select(CatalogItem.sku).where(CatalogItem.sku.in_(skus))
    )
    return set(rows)


def _clean_text(text: str | None) -> str | None:
    if not text:
        return text
    value = text
    for phrase, replacement in BANNED:
        if phrase in value.lower():
            value = re.sub(re.escape(phrase), replacement, value, flags=re.IGNORECASE)
    return value


_AMOUNT_RE = re.compile(r"bs\.?\s*(\d[\d.,]*)", re.IGNORECASE)
_SKU_TEXT_RE = re.compile(r"sku:?\s*([a-z0-9\-]{3,})", re.IGNORECASE)


def _parse_amount(raw: str) -> float | None:
    value = (raw or "").strip().rstrip(".,")
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    elif value.count(".") == 1:
        entero, decimales = value.split(".")
        if len(decimales) != 2:
            value = entero + decimales
    try:
        return float(value)
    except ValueError:
        return None


async def _allowed_prices(session: AsyncSession, sku: str) -> set[float]:
    """Precio de lista y promociones vigentes del SKU."""
    from decimal import Decimal

    from ..models import CatalogItem, ProductPromotion

    item = await session.scalar(
        select(CatalogItem).where(CatalogItem.sku == sku)
    )
    if item is None:
        return set()
    prices = {float(item.price)}
    promos = await session.scalars(
        select(ProductPromotion).where(ProductPromotion.sku == sku)
    )
    for promo in promos:
        prices.add(float(promo.price))
    return prices


async def _fix_prices(session: AsyncSession, reply) -> None:
    """Corrige montos que no coinciden con el producto citado.

    Solo actúa en fichas de un producto (no en totales del carrito).
    """
    skus: set[str] = set()
    for message in reply.messages:
        for section in message.sections or []:
            for row in section.get("rows") or []:
                sku = _sku_from_id(row.get("id"))
                if sku:
                    skus.add(sku)
        for button in message.buttons or []:
            sku = _sku_from_id(button.get("id"))
            if sku:
                skus.add(sku)
        for match in _SKU_TEXT_RE.finditer(message.text or ""):
            skus.add(match.group(1).upper())

    if len(skus) != 1:
        return
    if any("carrito" in (m.text or "").lower() for m in reply.messages):
        return
    if not any("precio" in (m.text or "").lower() for m in reply.messages):
        return

    allowed = await _allowed_prices(session, next(iter(skus)))
    if not allowed:
        return
    reference = min(allowed)

    for message in reply.messages:
        text = message.text or ""
        if "precio" not in text.lower():
            continue

        def _replace(match: re.Match) -> str:
            value = _parse_amount(match.group(1))
            if value is None:
                return match.group(0)
            if any(abs(value - price) <= 0.5 for price in allowed):
                return match.group(0)
            logger.warning(
                "Precio inventado %s para %s; se corrige a %s",
                match.group(1),
                next(iter(skus)),
                reference,
            )
            return f"Bs {reference:,.2f}"

        message.text = _AMOUNT_RE.sub(_replace, text)


async def sanitize(session: AsyncSession, reply, text: str | None):
    """Corrige la respuesta antes de enviarla. Nunca lanza."""
    from ..agent import AgentReply, Outbound  # local: evita import circular

    decision = intent.rules(text or "")

    # 1. Tema delicado: se responde SOLO con empatía, venga de donde venga.
    if decision.get("sensitive"):
        if reply_has_product(reply):
            logger.warning(
                "Respuesta con productos ante tema sensible; se reemplaza"
            )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=persona.empathy(decision.get("sensitive_topic")),
                    buttons=[
                        {"id": "human", "title": "Hablar con alguien"},
                        {"id": "catalog", "title": "Seguir con productos"},
                    ],
                )
            ]
        )

    # 2. Cliente enojado: nada de venta, solo la disculpa y el contacto humano.
    if decision.get("frustrated"):
        reply.messages = _strip_products(reply.messages)
        if not any(message.text for message in reply.messages):
            reply.messages = [
                Outbound(
                    kind="buttons",
                    text=persona.frustration(),
                    buttons=[{"id": "human", "title": "Hablar con alguien"}],
                )
            ]
        return reply

    # 3. Temas de política: se responde con la derivación, sin venta.
    topic = policy.detect(text)
    if topic:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=policy.reply(topic),
                    buttons=[
                        {"id": "human", "title": "Hablar con alguien"},
                        {"id": "catalog", "title": "Seguir con productos"},
                    ],
                )
            ]
        )

    # 4. Precios que no coinciden con el catálogo.
    try:
        await _fix_prices(session, reply)
    except Exception:  # noqa: BLE001 - no bloquear por el chequeo de precios
        logger.exception("No se pudo validar precios")

    # 5. Referencias a SKU inexistentes.
    ids: set[str] = set()
    for message in reply.messages:
        for section in message.sections or []:
            for row in section.get("rows") or []:
                sku = _sku_from_id(row.get("id"))
                if sku:
                    ids.add(sku)
        for button in message.buttons or []:
            sku = _sku_from_id(button.get("id"))
            if sku:
                ids.add(sku)
    known = await _known_skus(session, ids)

    messages = []
    for message in reply.messages:
        message.text = _clean_text(message.text)
        if message.sections:
            sections = []
            for section in message.sections:
                rows = []
                for row in section.get("rows") or []:
                    sku = _sku_from_id(row.get("id"))
                    if sku and sku not in known:
                        logger.warning("Se quita opción con SKU inexistente %s", sku)
                        continue
                    rows.append(row)
                if rows:
                    sections.append({**section, "rows": rows})
            message.sections = sections
        if message.kind == "list" and not message.sections:
            continue
        messages.append(message)

    if not messages:
        messages = [
            Outbound(
                text="No pude armar la respuesta. ¿Me lo repetís, por favor?"
            )
        ]

    reply.messages = messages
    return reply


def _strip_products(messages: list) -> list:
    """Quita imágenes y cualquier oferta (filas o botones de producto)."""
    kept = []
    for message in messages:
        if message.kind == "image":
            continue
        if message.buttons:
            message.buttons = [
                button
                for button in message.buttons
                if not _sku_from_id(button.get("id"))
            ]
        if message.sections:
            sections = []
            for section in message.sections:
                rows = [
                    row
                    for row in section.get("rows") or []
                    if not _sku_from_id(row.get("id"))
                ]
                if rows:
                    sections.append({**section, "rows": rows})
            message.sections = sections
        if message.kind == "list" and not message.sections:
            continue
        kept.append(message)
    return kept


def reply_has_product(reply) -> bool:
    for message in reply.messages:
        if message.kind in ("image", "product", "catalog"):
            return True
        for section in message.sections or []:
            for row in section.get("rows") or []:
                if _sku_from_id(row.get("id")):
                    return True
        for button in message.buttons or []:
            if _sku_from_id(button.get("id")):
                return True
    return False
