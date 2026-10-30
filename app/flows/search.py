"""Tarjetas de producto: fotos, precios y menú de opciones.

Extraído de `agent.py` (etapa 1 de la búsqueda).
"""

from __future__ import annotations

from decimal import Decimal

from ..whatsapp import Outbound
from .text import card_description


def _truncate(texto: str, limit: int) -> str:
    import re

    clean = re.sub(r"\s+", " ", texto or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _precio(product: dict) -> str:
    price = product.get("promo_price") or product.get("price")
    try:
        return f"{Decimal(str(price)):,.2f}"
    except Exception:  # noqa: BLE001 - precio ya formateado
        return str(price)


def cards(
    products: list[dict], maximo: int = 5, consulta: str = ""
) -> list[Outbound]:
    """Lista de opciones (texto + menú), sin fotos.

    El cliente ve nombre y precio, elige una opción y recién ahí se muestra la
    foto con la ficha completa. Antes llegaban tres fotos y además el menú con
    los mismos productos: información duplicada.
    """
    from ..agent import _fold_word
    from ..services import emoji

    seleccionados: list[dict] = []
    vistas: set[str] = set()
    for producto in products:
        clave = _fold_word(producto.get("name") or "")
        if clave in vistas:
            continue
        vistas.add(clave)
        seleccionados.append(producto)
        if len(seleccionados) >= maximo:
            break
    if not seleccionados:
        return []

    primero = seleccionados[0]
    tema = " ".join(
        [
            str(primero.get("category") or ""),
            str(primero.get("name") or ""),
        ]
    )
    icono = emoji.para(tema)

    lineas: list[str] = []
    for index, product in enumerate(seleccionados, start=1):
        nombre = _truncate(product.get("name") or "Producto", 58)
        linea = f"{index}. {nombre} — Bs {_precio(product)}"
        marca = (product.get("brand") or "").strip()
        if marca:
            linea += f" · {marca}"
        lineas.append(linea)

    total = len(seleccionados)
    if consulta:
        # Confirmar lo que se entendió: el cliente ve que se buscó eso.
        encabezado = f"Buscás *{consulta[:60]}* {icono}: "
        encabezado += (
            "esta es la opción:"
            if total == 1
            else f"estas son las {total}:"
        )
    else:
        encabezado = (
            f"Encontré *1 opción* {icono}:"
            if total == 1
            else f"Encontré *{total} opciones* {icono}:"
        )
    # La invitación va en el cuerpo del menú, no acá: repetirla dos veces
    # se lee como si el bot no escuchara.
    mensaje = f"{encabezado}\n\n" + "\n".join(lineas)

    rows = [
        {
            "id": f"product:{product['sku']}",
            "title": _truncate(f"{index}. {product.get('name') or ''}", 24),
            "description": (
                f"Bs {_precio(product)}"
                + (
                    f" · {product.get('brand')}"
                    if (product.get("brand") or "").strip()
                    else ""
                )
            )[:72],
        }
        for index, product in enumerate(seleccionados, start=1)
    ]
    return [
        Outbound(text=mensaje[:4096]),
        Outbound(
            kind="list",
            text="Tocá una opción para ver la foto y la ficha 👇",
            button_text="Ver opciones",
            sections=[{"title": "Opciones", "rows": rows}],
        ),
    ]


async def price_reply(
    agent,
    session,
    contact,
    raw: str,
    direction: str,
    base_hint: str | None = None,
):
    """Lista los artículos más baratos (o más caros) del rubro vigente."""
    import re

    from sqlalchemy import select

    from ..agent import (
        Toolbox,
        _clean_query,
        _price_intent,
        conversation_state,
    )
    from ..models import Conversation, Message
    from ..replies import AgentReply
    from ..whatsapp import Outbound

    """Lista los artículos más baratos (o más caros) del rubro vigente."""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    state = (
        await conversation_state.get_state(session, conversacion.id)
        if conversacion is not None
        else None
    )
    base = (base_hint or "").strip() or (
        (getattr(state, "category", None) or "") if state else ""
    ).strip()
    if not base and conversacion is not None:
        base = (conversacion.last_query or "").strip()
    base = _clean_query(base)
    if not base and conversacion is not None:
        # Sin rubro guardado: se toma el último mensaje del cliente que
        # no haya sido otro pedido de precio ("tienes taladros?").
        previos = (
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversacion.id,
                    Message.direction == "in",
                )
                .order_by(Message.created_at.desc())
                .limit(6)
            )
        ).all()
        for previo in previos:
            candidato = _clean_query(previo.text or "")
            if len(candidato) >= 4 and not _price_intent(candidato):
                base = candidato
                break
    if not base:
        return None

    resultado = await Toolbox(
        session, contact, agent.wa
    ).tool_search_products(query=base, limit=12)
    productos = resultado.get("products") or []
    if not productos:
        return None

    def precio(producto: dict) -> float:
        valor = producto.get("promo_price") or producto.get("price") or 0
        try:
            return float(valor)
        except (TypeError, ValueError):
            return 0.0

    productos.sort(key=precio, reverse=direction == "desc")
    singular = bool(
        re.search(
            r"\b(cu[aá]l|cu[aá]les)\b.*\b(m[aá]s\s+barat|menor\s+precio|precio\s+m[aá]s\s+bajo|"
            r"m[aá]s\s+car|mayor\s+precio)",
            raw or "",
            re.IGNORECASE,
        )
    )
    elegidos = productos[:1] if singular else productos[:3]
    rubro = ((getattr(state, "category", None) or base) if state else base).strip()
    if direction == "asc":
        texto_lead = (
            f"El más barato de {rubro} es este:"
            if singular
            else f"Estos son los más baratos de {rubro}:"
        )
    else:
        texto_lead = (
            f"El más caro de {rubro} es este:"
            if singular
            else f"Estos son los más caros de {rubro}:"
        )
    agent._trace(f"Orden por precio ({direction}): {rubro}")
    return AgentReply(
        [
            Outbound(text=texto_lead),
            *agent._search_cards(elegidos),
        ]
    )

