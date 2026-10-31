"""«Es caro»: la objeción más común y la que más ventas pierde.

Un vendedor no discute el precio: entiende, y muestra algo que sí entra en el
bolsillo del cliente. Eso es lo que hace este módulo con el catálogo real.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from ..models import Contact, Conversation
from . import catalog

OBJECION = re.compile(
    r"\b(es|est[aá]|muy|bastante|demasiado|un poco)?\s*car[oa]s?\b"
    r"|\bcar[ií]simo\w*"
    r"|\bno me alcanza\b"
    r"|\bfuera de (mi )?presupuesto\b"
    r"|\bmuy costoso\b"
    r"|\bno tengo (tanto|esa plata|esa cantidad)\b"
    r"|\bes mucho\b",
    re.IGNORECASE,
)

# Cuánto más barato tiene que ser para ofrecerlo.
TOPE = 0.85


def es_objecion(texto: str) -> bool:
    return bool(OBJECION.search(texto or ""))


def _precio(producto) -> float:
    try:
        return float(
            getattr(producto, "promo_price", None) or producto.price or 0
        )
    except (TypeError, ValueError):
        return 0.0


async def ultimo_producto(session, contact: Contact):
    """Producto del que se está hablando ahora."""
    from . import conversation_state

    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return None
    estado = await conversation_state.get_state(session, conversacion.id)
    sku = (getattr(estado, "last_sku", None) or "").strip()
    if not sku:
        # El estado no siempre guarda el último producto: se usa el historial.
        from . import memoria_cliente

        visto = await memoria_cliente.ultimo_visto(session, contact)
        sku = (visto or {}).get("sku") or ""
    if not sku:
        return None
    return await catalog.get_item(session, sku)


async def mas_baratos(
    session, producto, contact=None, limite: int = 3
) -> list[dict]:
    """Alternativas del mismo rubro, más baratas que la que le interesó."""
    precio = _precio(producto)
    if precio <= 0:
        return []
    categoria = (getattr(producto, "category", None) or "").strip()
    if not categoria:
        return []
    tope = precio * TOPE
    from ..agent import Toolbox

    caja = Toolbox(session, contact=contact, wa=None)
    resultado = await caja.tool_search_products(
        query=categoria,
        category=categoria,
        max_price=tope,
        limit=limite + 3,
        ignore_state=True,
    )
    filas = resultado.get("products") or []
    # Tiene que ser el mismo tipo de producto, no un accesorio: una cabecera
    # de cama no reemplaza a un colchón caro.
    sustantivo = (producto.name or "").split()[0].lower() if producto.name else ""
    salida = []
    for fila in filas:
        try:
            valor = float(fila.get("promo_price") or fila.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if valor <= 0 or valor >= precio:
            continue
        nombre = (fila.get("name") or "").lower()
        if sustantivo and sustantivo not in nombre:
            continue
        salida.append(fila)
    salida.sort(key=lambda fila: float(fila.get("promo_price") or fila["price"]))
    return salida[:limite]
