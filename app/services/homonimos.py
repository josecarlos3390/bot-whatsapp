"""Palabras que significan dos cosas distintas en el catálogo.

«Consola» es un mueble y también una consola de videojuegos. «Tinta» es
pintura y también insumo de impresora. Si el cliente no aclara, el bot no
debe afirmar que tiene lo uno ni lo otro: pregunta.
"""

from __future__ import annotations

import re

from . import catalog

# palabra -> significados (a/b) con las palabras que los identifican
HOMONIMOS: dict[str, dict] = {
    "consola": {
        "a": ("mueble", ("aparador", "bufetera", "mueble", "rack", "consola")),
        "b": (
            "videojuegos",
            ("playstation", "xbox", "nintendo", "videojuego", "joystick", "gamepad"),
        ),
        "pregunta": "¿Buscabas el mueble consola o una consola para jugar?",
    },
    "tinta": {
        "a": ("pintura", ("esmalte", "pintura", "latex", "látex", "barniz")),
        "b": ("impresora", ("toner", "tóner", "cartucho", "impresora")),
        "pregunta": "¿Buscabas pintura o tinta para impresora?",
    },
    "base": {
        "a": ("cama", ("cama", "somier", "colchon", "colchón")),
        "b": ("licuadora", ("licuadora", "batidora", "vaso", "jarra")),
        "pregunta": "¿La base es para la cama o para una licuadora?",
    },
}

# Palabras que ya definen el significado: no hace falta preguntar.
_ACLARAN = {
    "consola": ("jugar", "juego", "juegos", "playstation", "xbox", "nintendo", "mueble", "tv", "sala", "living"),
    "tinta": ("pintura", "pintar", "pared", "imprimir", "impresora", "toner"),
    "base": ("cama", "colchon", "colchón", "licuadora", "somier"),
}


def _palabras(texto: str) -> set[str]:
    return set(re.findall(r"[a-záéíóúñ0-9]{3,}", (texto or "").lower()))


def buscar(texto: str) -> dict | None:
    """Palabra ambigua del mensaje, si la hay."""
    palabras = _palabras(texto)
    for clave in HOMONIMOS:
        if clave in palabras:
            return {"palabra": clave, **HOMONIMOS[clave]}
    return None


def ya_aclaro(texto: str, palabra: str) -> bool:
    """¿El cliente ya dijo de qué está hablando?"""
    return bool(_palabras(texto) & set(_ACLARAN.get(palabra, ())))


async def significado(session, palabra: str) -> str:
    """Qué significado aparece en el catálogo: «a», «b», «ambos» o «ninguno»."""
    datos = HOMONIMOS[palabra]
    filas = await catalog.search_items(session, palabra, limit=8)
    if not filas:
        return "ninguno"
    nombres = " ".join(f"{f.name} {f.category}".lower() for f in filas)
    tiene_a = any(clave in nombres for clave in datos["a"][1])
    tiene_b = any(clave in nombres for clave in datos["b"][1])
    if tiene_a and tiene_b:
        return "ambos"
    if tiene_a:
        return "a"
    if tiene_b:
        return "b"
    return "ninguno"


def aclarar(palabra: str, conocido: str) -> dict:
    """Pregunta y dos opciones de búsqueda."""
    datos = HOMONIMOS[palabra]
    etiqueta_a = datos["a"][0]
    etiqueta_b = datos["b"][0]
    # Si el catálogo solo tiene uno de los dos, se ofrece ese primero.
    if conocido == "b":
        etiqueta_a, etiqueta_b = etiqueta_b, etiqueta_a
    return {
        "texto": (
            f"«{palabra.capitalize()}» puede ser dos cosas distintas: "
            f"{etiqueta_a} o {etiqueta_b}. {datos['pregunta']}"
        ),
        "botones": [
            {"id": f"find:{palabra} {etiqueta_a}", "title": etiqueta_a[:20]},
            {"id": f"find:{palabra} {etiqueta_b}", "title": etiqueta_b[:20]},
        ],
    }
