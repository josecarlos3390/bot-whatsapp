"""Emojis por tema: un detalle visual, sin exagerar.

Se usa uno por mensaje, alineado con lo que se está mostrando.
"""

from __future__ import annotations

# Palabra clave en el texto → emoji. Se busca de arriba hacia abajo.
_TEMAS: list[tuple[str, str]] = [
    ("halloween", "🎃"),
    ("navidad", "🎄"),
    ("televisor", "📺"),
    ("tv ", "📺"),
    ("colch", "🛏️"),
    ("almohada", "🛏️"),
    ("helader", "🧊"),
    ("refriger", "🧊"),
    ("lavadora", "🌀"),
    ("lavarropa", "🌀"),
    ("aire", "❄️"),
    ("ventilador", "🌬️"),
    ("parrilla", "🔥"),
    ("asador", "🔥"),
    ("taladro", "🔧"),
    ("herramienta", "🔧"),
    ("llave", "🔧"),
    ("pintura", "🎨"),
    ("lámpara", "💡"),
    ("lampara", "💡"),
    ("foco", "💡"),
    ("ilumin", "💡"),
    ("sofa", "🛋️"),
    ("sofá", "🛋️"),
    ("sillón", "🛋️"),
    ("sillon", "🛋️"),
    ("colchoneta", "🛏️"),
    ("cocina", "🍳"),
    ("olla", "🍳"),
    ("vajilla", "🍽️"),
    ("cubierto", "🍽️"),
    ("baño", "🚿"),
    ("bano", "🚿"),
    ("ducha", "🚿"),
    ("jardín", "🌿"),
    ("jardin", "🌿"),
    ("planta", "🌿"),
    ("piscina", "🏊"),
    ("vela", "🕯️"),
    ("decor", "🏡"),

    ("plancha", "💇"),
    ("secador", "💇"),
    ("bicicleta", "🚲"),
    ("deporte", "⚽"),
    ("juguete", "🧸"),
    ("mascota", "🐾"),
    ("oficina", "💼"),
    ("escritorio", "💼"),
]


def para(texto: str, defecto: str = "🛍️") -> str:
    """Emoji que mejor representa el texto."""
    valor = f"{(texto or '').lower()} "
    for clave, emoji in _TEMAS:
        if clave in valor:
            return emoji
    return defecto
