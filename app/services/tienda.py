"""Dónde encontrarlo: responder la tienda sin repetir la ficha.

«¿En qué tienda puedo encontrarlo?» es una pregunta de disponibilidad, no un
pedido de producto. Repetir la ficha ahí deja al cliente sin respuesta.
"""

from __future__ import annotations

import re

from . import knowledge

# Pregunta por tienda / sucursal / dónde retirar.
TIENDA = re.compile(
    r"\b(en\s+qu[eé]|en\s+que|qu[eé]|que|cu[aá]l)\s+"
    r"(tienda|sucursal|local)\b"
    r"|\b(d[oó]nde|donde)\s+(lo\s+)?(puedo\s+)?(encontrar|ver|retirar|comprar|est[aá])\b"
    r"|\b(tienen|hay)\s+(stock\s+)?en\s+(la\s+)?(tienda|sucursal)\b"
    r"|\bretiro\s+en\s+tienda\b",
    re.IGNORECASE,
)


def pregunta_tienda(texto: str) -> bool:
    return bool(TIENDA.search(texto or ""))


def tiendas() -> list[dict]:
    """Sucursales publicadas, sacadas de la base de conocimiento."""
    articulos = knowledge.search("sucursales direcciones horarios", limit=1)
    if not articulos:
        return []
    contenido = articulos[0].get("content") or ""
    salida: list[dict] = []
    actual: dict | None = None
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if limpia.startswith("## Tienda"):
            if actual:
                salida.append(actual)
            actual = {"titulo": limpia[3:].strip(), "direccion": ""}
        elif actual and limpia.lower().startswith("- dirección"):
            actual["direccion"] = limpia.split(":", 1)[-1].strip()
    if actual:
        salida.append(actual)
    return [tienda for tienda in salida if tienda["direccion"]]


def responder(nombre_producto: str = "", stock: int | None = None) -> str:
    """Lista de tiendas + qué hacer para confirmar stock."""
    lista = tiendas()
    if not lista:
        return (
            "Podés encontrarlo en cualquiera de nuestras tiendas 🏬 "
            "¿Querés que te pase la dirección de la más cercana?"
        )
    lineas = [
        f"Lo tenemos en nuestras *{len(lista)} tiendas* de Santa Cruz 🏬",
        "",
    ]
    for tienda in lista:
        lineas.append(f"📍 *{tienda['titulo']}*")
        lineas.append(f"   {tienda['direccion']}")
    lineas.append("")
    if stock is not None:
        lineas.append(
            f"Hay *{stock} unidades* disponibles en depósito central."
        )
    lineas.append(
        "No manejamos stock separado por tienda: cualquiera de las tres te lo "
        "consigue, y el retiro se coordina desde la tienda de Av. Banzer."
    )
    lineas.append("")
    lineas.append(
        "¿Querés que te reserve una unidad o preferís envío a domicilio?"
    )
    return "\n".join(lineas)

async def stock_por_tienda(session, sku: str) -> dict[str, int]:
    """Stock por sucursal, si el proveedor lo informa."""
    from . import pricing

    try:
        oferta = await pricing.get_offer(session, sku, 1)
    except Exception:  # noqa: BLE001 - sin dato, se responde el stock total
        return {}
    return dict(getattr(oferta, "stock_by_store", None) or {})


def responder_con_tiendas(
    nombre: str, stock_total: int, por_tienda: dict[str, int]
) -> str:
    """Lista qué tienda tiene unidades, cuando el dato existe."""
    if not por_tienda:
        return responder(nombre, stock_total)

    from ..config import settings

    nombres = settings.sap_store_map
    con_stock = [
        (nombres.get(codigo, codigo), cantidad)
        for codigo, cantidad in por_tienda.items()
        if cantidad > 0
    ]
    corto = (nombre or "ese producto")[:52]
    if not con_stock:
        return (
            f"*{corto}* no tiene unidades en ninguna tienda ahora 📦\n"
            "¿Querés que te avise cuando llegue o buscamos algo parecido?"
        )
    con_stock.sort(key=lambda par: par[1], reverse=True)
    detalle = "\n".join(
        f"• {tienda}: {cantidad} unidades" for tienda, cantidad in con_stock
    )
    return (
        f"*{corto}* está disponible en:\n{detalle}\n\n"
        "¿Te lo reservo en la que te quede más cerca?"
    )
