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
    if stock is not None:
        lineas.append("")
        lineas.append(
            f"Hay *{stock} unidades* en stock central: se puede retirar o "
            "enviar a domicilio en 24 a 48 horas."
        )
    lineas.append("")
    lineas.append(
        "¿Querés que te reserve una unidad en la tienda que te quede más "
        "cerca?"
    )
    return "\n".join(lineas)
