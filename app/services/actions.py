"""Acciones explícitas del cliente: lo que pidió, se le muestra.

Los guards de calidad (coherencia, repetición, cambio de enfoque) existen para
no repetir listados y no inventar temas. Pero cuando el cliente toca un botón
pidió algo concreto: tapar esa respuesta es un error grave.
"""

from __future__ import annotations

# Prefijos e identificadores de botones/comandos.
PREFIJOS = (
    "product:",
    "add:",
    "qty:",
    "remove:",
    "cat:",
    "sub:",
    "type:",
    "see:",
    "uso:",
    "refine:",
    "idea:",
    "find:",
    "price:",
    "doc:",
    "checkout",
    "pay:",
    "confirm:",
    "cancel:",
)

EXACTOS = {
    "catalog",
    "cart",
    "estado",
    "human",
    "asesor",
    "search",
    "more",
    "filter",
    "menu",
    "inicio",
}


def es_accion(texto: str) -> bool:
    """¿El mensaje es un botón o un comando del cliente?"""
    valor = (texto or "").strip().lower()
    if not valor:
        return False
    if valor in EXACTOS:
        return True
    return any(valor.startswith(prefijo) for prefijo in PREFIJOS)
