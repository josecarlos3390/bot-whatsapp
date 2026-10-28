"""Helpers de texto compartidos por los flujos."""

from __future__ import annotations

import re


def card_description(value: str, limit: int = 160) -> str:
    """Descripción corta para la tarjeta del producto."""
    clean = re.sub(r"<[^>]+>", " ", value or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= limit:
        return clean
    cut = clean[: limit - 1].rsplit(" ", 1)[0].rstrip()
    return (cut or clean[: limit - 1]).rstrip() + "…"
