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


def cards(products: list[dict]) -> list[Outbound]:
    """Tarjetas visuales: hasta 3 fotos y una lista con las opciones."""
    from ..agent import _fold_word

    selected: list[dict] = []
    vistas: set[str] = set()
    for producto in products:
        clave = _fold_word(producto.get("name") or "")
        if clave in vistas:
            continue
        vistas.add(clave)
        selected.append(producto)
        if len(selected) == 3:
            break
    if not selected:
        return []
    messages: list[Outbound] = []
    for index, product in enumerate(selected, start=1):
        price = product.get("promo_price") or product.get("price")
        try:
            price_text = f"{Decimal(str(price)):,.2f}"
        except Exception:  # noqa: BLE001 - precio ya formateado
            price_text = str(price)
        caption = (
            f"*{index}. {product['name']}*\n"
            f"Precio: Bs {price_text}"
        )
        brand = (product.get("brand") or "").strip()
        if brand:
            caption += f"\nMarca: {brand}"
        category = (product.get("category") or "").strip()
        if category:
            caption += f"\nCategoría: {category}"
        description = card_description(
            product.get("description") or ""
        )
        if description:
            caption += f"\nDescripción: {description}"
        image_url = (product.get("image_url") or "").strip()
        if image_url.startswith(("http://", "https://")):
            messages.append(
                Outbound(
                    kind="image",
                    url=image_url,
                    text=caption[:1024],
                )
            )
        else:
            messages.append(Outbound(text=caption[:4096]))
    # En vez de botones "Agregar 1/2/3" (que no dicen a qué producto
    # corresponden), una lista con el nombre y el precio de cada opción.
    rows = []
    for index, product in enumerate(selected, start=1):
        price = product.get("promo_price") or product.get("price")
        try:
            price_text = f"{Decimal(str(price)):,.2f}"
        except Exception:  # noqa: BLE001
            price_text = str(price)
        detail = f"Bs {price_text}"
        brand = (product.get("brand") or "").strip()
        if brand:
            detail += f" · {brand}"
        rows.append(
            {
                "id": f"product:{product['sku']}",
                "title": _truncate(
                    f"{index}. {product['name']}", 24
                ),
                "description": detail[:72],
            }
        )
    total = len(selected)
    encabezado = (
        "Te muestro la opción. Decime si te sirve y te paso el detalle:"
        if total == 1
        else f"Son {total} opciones. Decime cuál te interesa y te muestro el detalle:"
    )
    messages.append(
        Outbound(
            kind="list",
            text=encabezado,
            button_text="Ver opciones",
            sections=[{"title": "Opciones", "rows": rows}],
        )
    )
    return messages



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

