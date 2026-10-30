"""Emojis con criterio: decoran la charla, pero no en momentos delicados.

Un emoji en un saludo suma cercanía; en un reclamo por un pedido roto resta
seriedad. Esta capa decide cuándo sí y cuándo no.
"""

from __future__ import annotations

import re

from . import policy

# Rango amplio de emojis y símbolos decorativos.
_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\u2600-\u27BF" "\u2B00-\u2BFF" "\uFE0F" "]"
)

# Temas donde el emoji sobra: el cliente está molesto o es un tema formal.
_DELICADOS = re.compile(
    r"\b(reclamo|reclam[oa]|queja|devoluci[oó]n|devolver|cambio de producto|"
    r"roto|rota|fallad[oa]|no funciona|estafa|denuncia|abogado|garant[ií]a|"
    r"factura|reembolso|dinero|perd[ií]|robaron|mal[ií]simo|p[eé]simo|"
    r"harto|hart[oa]|enojad[oa]|furios[oa])\b",
    re.IGNORECASE,
)


def es_delicado(texto: str) -> bool:
    """¿Es un momento donde conviene hablar sin adornos?"""
    valor = texto or ""
    if _DELICADOS.search(valor):
        return True
    return policy.detect(valor) is not None


def limpiar(texto: str) -> str:
    """Quita emojis y deja el texto prolijo."""
    if not texto:
        return texto
    limpio = _EMOJI.sub("", texto)
    limpio = re.sub(r"[ \t]{2,}", " ", limpio)
    limpio = re.sub(r" +\n", "\n", limpio)
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)
    return limpio.strip()


def tiene(texto: str) -> bool:
    return bool(_EMOJI.search(texto or ""))
