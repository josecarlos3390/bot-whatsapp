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

