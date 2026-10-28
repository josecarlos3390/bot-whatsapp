"""Capa de canales: el mismo bot en WhatsApp, Instagram, Messenger y web.

Diseño técnico completo: `docs/capa-canales.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import (
    INSTAGRAM,
    MESSENGER,
    WEBCHAT,
    WHATSAPP,
    Capabilities,
    Inbound,
)
from .render import Rendered, render, render_reply

__all__ = [
    "INSTAGRAM",
    "MESSENGER",
    "WEBCHAT",
    "WHATSAPP",
    "Capabilities",
    "Inbound",
    "Rendered",
    "render",
    "render_reply",
]


@dataclass
class Envio:
    """Resultado de intentar entregar un mensaje."""

    ok: bool
    external_id: str = ""
    error: str = ""
    entregados: int = 1
    extra: dict = field(default_factory=dict)
