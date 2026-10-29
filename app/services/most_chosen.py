"""«Mostrame las más elegidas»: una respuesta concreta, con justificación.

El bot preguntaba «¿alguna marca en particular o te muestro las más elegidas?»
y al responder «las más elegidas» buscaba esa frase como producto: no
encontraba nada y contestaba «no tengo eso exacto». Acá se resuelve el pedido
con lo que hay: ventas, descuentos y stock.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, ProductSalesStat
from ..replies import AgentReply
from ..whatsapp import Outbound
from . import catalog

logger = logging.getLogger(__name__)

INTENT_RE = re.compile(
    r"\b(m[aá]s\s+elegid[oa]s?|las\s+elegidas|populares|recomendad[oa]s?|"
    r"lo\s+m[aá]s\s+vendido|m[aá]s\s+buscad[oa]s?|las\s+mejores)\b",
    re.IGNORECASE,
)


def is_most_chosen(text: str) -> bool:
    return bool(INTENT_RE.search(text or ""))


async def _base(session: AsyncSession, contact: Contact) -> str:
    """Rubro sobre el que se pregunta: estado y última consulta."""
    from . import conversation_state

    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return ""
    estado = await conversation_state.get_state(session, conversacion.id)
    base = (getattr(estado, "category", None) or "").strip()
    if not base:
        base = (conversacion.last_query or "").strip()
    return catalog.primary_term(base) or base


async def _ventas(session: AsyncSession, skus: list[str]) -> dict[str, int]:
    if not skus:
        return {}
    filas = (
        await session.scalars(
            select(ProductSalesStat).where(ProductSalesStat.sku.in_(skus))
        )
    ).all()
    return {
        fila.sku: int(fila.units_30d or 0) or int(fila.units_90d or 0)
        for fila in filas
    }


def _con_marca(ordenados: list, productos: list, policy) -> list:
    """Asegura que la marca prioritaria del portal esté entre las elegidas."""
    marca = (getattr(policy, "brand", None) or "").strip().lower()
    if not marca:
        return ordenados
    if ordenados and (
        str(getattr(ordenados[0], "brand", "") or "").strip().lower()
        == marca
    ):
        return ordenados
    candidato = next(
        (
            item
            for item in productos
            if str(getattr(item, "brand", "") or "").strip().lower() == marca
        ),
        None,
    )
    if candidato is None:
        return ordenados
    return [candidato, *ordenados[:-1]]


async def reply(
    agent, session: AsyncSession, contact: Contact, raw: str
) -> AgentReply | None:
    """Responde el pedido de «las más elegidas» del rubro vigente."""
    from ..agent import Toolbox, _clean_query

    base = await _base(session, contact)
    if not base:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Decime de qué rubro querés ver las más elegidas "
                        "(por ejemplo colchones, televisores o taladros) y te "
                        "muestro las principales."
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    productos = await catalog.search_items(session, base, limit=12)
    if not productos:
        return None

    from . import rule_apply, rule_policy

    policy = await rule_policy.build(session, raw, category=base)
    productos = rule_apply.ordenar(productos, policy)
    ventas = await _ventas(session, [p.sku for p in productos])
    con_ventas = [p for p in productos if ventas.get(p.sku, 0) > 0]

    if con_ventas:
        ordenados = sorted(
            con_ventas, key=lambda p: ventas.get(p.sku, 0), reverse=True
        )[:3]
        ordenados = _con_marca(ordenados, productos, policy)
        criterio = "Fueron las más vendidas de los últimos 30 días."
    else:
        # Sin historial de ventas: descuento y stock, y se dice tal cual.
        def puntaje(item) -> tuple[int, int]:
            attributes = item.attributes if isinstance(item.attributes, dict) else {}
            con_descuento = 1 if attributes.get("promo_price") else 0
            return (con_descuento, item.stock or 0)

        ordenados = sorted(productos, key=puntaje, reverse=True)[:3]
        ordenados = _con_marca(ordenados, productos, policy)
        criterio = (
            "No tengo el ranking de ventas de este rubro, así que te muestro "
            "las que tienen descuento y más disponibilidad."
        )

    if not ordenados:
        return None

    toolbox = Toolbox(session, contact, agent.wa)
    tarjetas = [Toolbox._product(item) for item in ordenados]
    await toolbox._attach_promotions(tarjetas)

    titulo = (
        f"Estas son las más elegidas de *{base}*:"
        if con_ventas
        else f"Estas son las opciones más fuertes de *{base}*:"
    )
    lead = f"{titulo}\n\n{criterio}"
    agent._trace(f"Más elegidas: {base}")
    from . import rule_apply

    respuesta = AgentReply(
        [
            Outbound(text=lead),
            *agent._search_cards(tarjetas),
        ]
    )
    return await rule_apply.anexar_preguntas(
        session, raw, respuesta, categoria=base
    )


BARATOS_RE = re.compile(
    r"\b(m[aá]s\s+barat[oa]s?|m[aá]s\s+econ[oó]mic[oa]s?|"
    r"lo\s+m[aá]s\s+barato|econ[oó]micos)\b",
    re.IGNORECASE,
)


def is_cheapest(text: str) -> bool:
    return bool(BARATOS_RE.search(text or ""))


async def reply_cheapest(
    agent, session: AsyncSession, contact: Contact, raw: str
) -> AgentReply | None:
    """Los más económicos del rubro vigente, con el precio de entrada."""
    from ..agent import Toolbox

    base = await _base(session, contact)
    if not base:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Decime de qué rubro querés ver los más económicos "
                        "(por ejemplo colchones, televisores o taladros) y te "
                        "muestro desde qué precio arrancan."
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    productos = await catalog.search_items(session, base, limit=12)
    if not productos:
        return None

    from . import rule_apply, rule_policy

    policy = await rule_policy.build(session, raw, category=base)
    productos = rule_apply.ordenar(productos, policy)

    def precio(item) -> float:
        try:
            return float(item.price or 0)
        except (TypeError, ValueError):
            return 0.0

    con_precio = [item for item in productos if precio(item) > 0]
    ordenados = sorted(con_precio, key=precio)[:3]
    ordenados = _con_marca(ordenados, productos, policy)
    if not ordenados:
        return None

    toolbox = Toolbox(session, contact, agent.wa)
    tarjetas = [Toolbox._product(item) for item in ordenados]
    await toolbox._attach_promotions(tarjetas)

    desde = precio(ordenados[0])
    agent._trace(f"Más económicos: {base}")
    respuesta = AgentReply(
        [
            Outbound(
                text=(
                    f"Estos son los más económicos de *{base}*:\n\n"
                    f"Arrancan en Bs {desde:,.0f}. Te los ordené de menor a "
                    "mayor precio."
                ).replace(",", ".")
            ),
            *agent._search_cards(tarjetas),
        ]
    )
    return await rule_apply.anexar_preguntas(
        session, raw, respuesta, categoria=base
    )
