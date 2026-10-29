"""Aplicar las reglas del portal a los caminos nuevos.

Las reglas de área (marca prioritaria, promociones) se aplicaban en la
búsqueda y en las respuestas de la IA. Los atajos nuevos («las más elegidas»,
«los más económicos», ideas y relacionados) buscaban en el catálogo sin
respetarlas. Acá se ordena la lista según esas reglas antes de mostrarla.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ProductPromotion
from . import rule_policy

logger = logging.getLogger(__name__)


def _precio(producto) -> float:
    for clave in ("promo_price", "price"):
        valor = (
            producto.get(clave)
            if isinstance(producto, dict)
            else getattr(producto, clave, None)
        )
        if valor:
            try:
                return float(valor)
            except (TypeError, ValueError):
                continue
    return 0.0


def _marca(producto) -> str:
    if isinstance(producto, dict):
        return str(producto.get("brand") or "").strip().lower()
    return str(getattr(producto, "brand", "") or "").strip().lower()


def _sku(producto) -> str:
    if isinstance(producto, dict):
        return str(producto.get("sku") or "")
    return str(getattr(producto, "sku", "") or "")


async def descuentos(
    session: AsyncSession, skus: list[str]
) -> dict[str, float]:
    """Mejor descuento vigente por SKU (las promos viven aparte del artículo)."""
    if not skus:
        return {}
    hoy = date.today()
    filas = (
        await session.scalars(
            select(ProductPromotion).where(
                ProductPromotion.sku.in_(skus)
            )
        )
    ).all()
    mejores: dict[str, float] = {}
    for fila in filas:
        if fila.valid_from and fila.valid_from > hoy:
            continue
        if fila.valid_to and fila.valid_to < hoy:
            continue
        try:
            valor = float(fila.discount_percent or 0)
        except (TypeError, ValueError):
            continue
        if valor > mejores.get(fila.sku, 0):
            mejores[fila.sku] = valor
    return mejores


def ordenar(
    productos: list,
    policy: rule_policy.RulePolicy,
    promos: dict[str, float] | None = None,
) -> list:
    """Prioriza la marca y las promociones que pide el portal."""
    if not productos or not policy.has_product_rules:
        return productos
    promos = promos or {}

    def puntaje(producto) -> tuple:
        prioridad_marca = 0
        if policy.brand:
            prioridad_marca = (
                1 if _marca(producto) == policy.brand.lower() else 0
            )
        descuento = promos.get(_sku(producto), 0.0)
        if policy.promotion_min is not None:
            # Con regla de promociones: primero las que superan el mínimo y,
            # entre esas, el mayor descuento.
            cumple = 1 if descuento >= policy.promotion_min else 0
            return (prioridad_marca, cumple, descuento)
        return (prioridad_marca, -_precio(producto))

    return sorted(productos, key=puntaje, reverse=True)


async def aplicar(
    session: AsyncSession,
    texto: str,
    productos: list,
    *,
    categoria: str | None = None,
) -> list:
    """Ordena la lista según las reglas activas (sin romper si algo falla)."""
    try:
        policy = await rule_policy.build(session, texto, category=categoria)
    except Exception:  # noqa: BLE001 - una regla no debe romper la venta
        logger.debug("No se pudo evaluar las reglas", exc_info=True)
        return productos
    if not policy.has_product_rules:
        return productos
    promos = await descuentos(session, [_sku(p) for p in productos])
    ordenados = ordenar(productos, policy, promos)
    logger.info(
        "Reglas aplicadas en %s: marca=%s promo=%s",
        categoria or texto,
        policy.brand,
        policy.promotion_min,
    )
    return ordenados


async def preguntas_pendientes(
    session: AsyncSession,
    texto: str,
    *,
    categoria: str | None = None,
    limite: int = 2,
) -> list[str]:
    """Preguntas que el portal exige antes de cerrar la venta."""
    try:
        policy = await rule_policy.build(session, texto, category=categoria)
    except Exception:  # noqa: BLE001
        logger.debug("No se pudieron leer las preguntas", exc_info=True)
        return []
    return list(policy.questions)[:limite]


async def anexar_preguntas(
    session: AsyncSession,
    texto: str,
    reply,
    *,
    categoria: str | None = None,
):
    """Agrega las preguntas obligatorias al final de la respuesta."""
    from ..whatsapp import Outbound

    preguntas = await preguntas_pendientes(
        session, texto, categoria=categoria
    )
    if not preguntas or reply is None or not getattr(reply, "messages", None):
        return reply
    ya = any(
        pregunta.lower() in (mensaje.text or "").lower()
        for mensaje in reply.messages
        for pregunta in preguntas
    )
    if ya:
        return reply
    texto_preguntas = " ".join(preguntas)
    reply.messages.append(
        Outbound(text=f"Para asesorarte mejor: {texto_preguntas}")
    )
    return reply
