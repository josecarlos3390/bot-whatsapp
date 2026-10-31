"""Pedidos vagos y cuestionamientos: cuando el cliente no dijo qué quiere.

«Algo para mí» no es un producto: si el bot busca literalmente, muestra
almohadas y queda mal. Y «¿por qué me mostrás eso?» merece una respuesta, no
otra ficha.
"""

from __future__ import annotations

import re

# Pide algo sin decir qué: "algo para mí", "sorprendeme", "véndeme algo".
VAGO = re.compile(
    r"^(algo|alguna cosa|una cosa|cualquier cosa)\b"
    r"|\b(algo|una cosa)\s+(para|pa)\s+(mi|m[ií]|vos|regalar)\b"
    r"|\b(sorprendeme|sorpr[endé]ndeme|v[eé]ndeme algo|vende algo|vendeme algo|"
    r"mostrame algo|dame algo|"
    r"dame algo|recomendame algo|qu[eé] me recomend[aá]s|algo lindo|"
    r"algo interesante|algo bueno|algo barato|nada interesante)\b",
    re.IGNORECASE,
)

# Se queja o pregunta por qué le mostraron algo.
CUESTIONA = re.compile(
    r"\b(por\s*qu[eé]|porque)\s+(me\s+)?("
    r"mostr[aá]s|mostr[aá]|mostraste|mostro|suger[ií]s|sugieres|sugiere|"
    r"sugiri[oó]|sugeriste|"
    r"recomend[aá]s|recomiendas|recomend[oó]|ense[nñ]as|das|diste|"
    r"ofrec[eé]s|ofreces|pusiste"
    r")\b"
    r"|\bno\s+te\s+ped[ií]\b"
    r"|\bqu[eé]\s+tiene\s+que\s+ver\b"
    r"|\bpara\s+qu[eé]\s+me\s+mostr[aá]s\b",
    re.IGNORECASE,
)


def es_vago(texto: str) -> bool:
    """¿Pide algo sin decir qué?"""
    return bool(VAGO.search(texto or ""))


def es_cuestionamiento(texto: str) -> bool:
    """¿Está cuestionando una sugerencia?"""
    return bool(CUESTIONA.search(texto or ""))


def pregunta_vago() -> str:
    return (
        "Justo eso quiero evitar: mostrarte cosas al azar 😅\n"
        "¿Para qué lo querés? Así te muestro tres opciones que sirvan."
    )


def botones_vago() -> list[dict]:
    return [
        {"id": "cat:dormitorio", "title": "Para descansar"},
        {"id": "cat:cocina", "title": "Para la cocina"},
        {"id": "cat:herramientas", "title": "Herramientas"},
    ]


def disculpa(que: str = "") -> str:
    """Respuesta a «¿por qué me mostrás eso?»."""
    detalle = f"*{que}* " if que else ""
    return (
        f"Tenés razón y te pido disculpas: {detalle}no era lo que pediste. "
        "Me adelanté.\n\n"
        "Contame para qué lo necesitás y te muestro solo eso."
    )


def botones_disculpa() -> list[dict]:
    return [
        {"id": "catalog", "title": "Ver categorías"},
        {"id": "human", "title": "Hablar con asesor"},
    ]

# Pide que le muestren algo ya: acá conviene mostrar ofertas, no preguntar.
MOSTRAR = re.compile(
    r"\b(v[eé]ndeme|mostrame|dame|tirame|pasame)\s+algo\b"
    r"|\bnada\s+interesante\b"
    r"|\bqu[eé]\s+ten[eé]s\s+(de\s+)?(bueno|interesante|oferta)"
    r"|\balgo\s+(en\s+)?(descuento|oferta|promo)",
    re.IGNORECASE,
)


def quiere_ver_ofertas(texto: str) -> bool:
    """¿Pide que le mostremos algo concreto ahora?"""
    return bool(MOSTRAR.search(texto or ""))
