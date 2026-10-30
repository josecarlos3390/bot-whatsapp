"""Productos afines: cuando no hay lo que el cliente pide.

Si alguien manda la foto de un monitor y no vendemos monitores, lo honesto es
ofrecer lo más parecido del catálogo (televisores, soportes), no inventar
ideas con la IA ni devolver duchas por coincidir en la categoría.
"""

from __future__ import annotations

import logging

from . import catalog

logger = logging.getLogger(__name__)

# Objeto pedido -> términos del catálogo que sí existen y son afines.
AFINES: dict[str, tuple[str, ...]] = {
    "monitor": ("televisor", "soporte tv", "pantalla"),
    "computadora": ("laptop", "notebook", "teclado", "mouse"),
    "computador": ("laptop", "notebook", "teclado", "mouse"),
    "cpu": ("laptop", "notebook", "teclado", "mouse"),
    "impresora": ("tinta", "papel", "resma"),
    "tablet": ("celular", "televisor"),
    "celular": ("cargador", "audifonos", "funda"),
    "consola": ("televisor", "control", "joystick"),
    "secadora": ("lavadora", "tendedero"),
    "lavavajillas": ("lavadora", "cocina"),
    "microondas": ("horno", "cocina", "olla"),
    "freidora": ("olla", "sarten", "cocina"),
    "aspiradora": ("escoba", "trapeador", "limpieza"),
    "calentador": ("termotanque", "ducha", "calefon"),
    "ventilador de techo": ("ventilador", "lampara"),
    "colchon": ("almohada", "base", "somier"),
    "sofa": ("sillon", "sala", "mueble"),
    "escritorio": ("mesa", "silla", "estante"),
}


def terminos(objeto: str) -> tuple[str, ...]:
    """Términos afines para un objeto, sin repetir el propio objeto."""
    clave = (objeto or "").strip().lower()
    if not clave:
        return ()
    for nombre, lista in AFINES.items():
        if nombre in clave or clave in nombre:
            return tuple(t for t in lista if t not in clave)
    return ()


async def buscar(session, objeto: str, limite: int = 3) -> tuple[str, list]:
    """Primer término afín que tenga productos. Devuelve (término, productos)."""
    for termino in terminos(objeto):
        filas = await catalog.search_items(session, termino, limit=limite)
        if filas:
            logger.debug("Afín para %s: %s (%s)", objeto, termino, len(filas))
            return termino, filas
    return "", []
