"""«¿Tenés stock?»: responder por el producto que se acaba de ver.

El número exacto no se muestra (es información interna), pero el cliente
merece un sí o un no claro sobre el producto del que veníamos hablando.
"""

from __future__ import annotations

import re

PREGUNTA = re.compile(
    r"\b(hay|ten[eé]s|tienen|queda|quedan|tendr[aá]s)\s+"
    r"(stock|disponible|disponibles|unidades?)\b"
    r"|\bcu[aá]ntas?\s+(unidades?|hay)\b"
    r"|\b(hay|queda)\s+algo\b"
    r"|\best[aá]\s+disponible\b"
    r"|\bten[eé]s\s+(el|ese|este)\b",
    re.IGNORECASE,
)


def pregunta_stock(texto: str) -> bool:
    return bool(PREGUNTA.search(texto or ""))


def responder(nombre: str, stock: int, precio: str = "") -> str:
    """Respuesta corta según haya o no stock."""
    corto = (nombre or "ese producto")[:52]
    if stock <= 0:
        return (
            f"*{corto}* no tiene stock por ahora 📦\n"
            "¿Querés que te avise cuando llegue o buscamos algo parecido?"
        )
    extra = f" Está en {precio}." if precio else ""
    return (
        f"Sí, *{corto}* está disponible 👍{extra}\n"
        "¿Te lo agrego al carrito o te lo reservo?"
    )
