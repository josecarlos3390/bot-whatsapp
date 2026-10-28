"""Contrato de canales: qué necesita el bot para responder en otro lado.

El agente produce mensajes estructurados (texto, botones, listas, imágenes).
Cada canal tiene capacidades distintas; acá se declaran y se traducen.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Capabilities:
    """Lo que un canal puede mostrar."""

    name: str
    lists: bool = False          # mensajes de lista (WhatsApp)
    buttons: int = 0             # botones o respuestas rápidas
    images: bool = True
    markdown: str = "plain"      # whatsapp | markdown | html | plain
    max_text: int = 2000
    max_buttons_text: int = 20


# Perfiles de cada canal.
WHATSAPP = Capabilities(
    name="whatsapp",
    lists=True,
    buttons=3,
    images=True,
    markdown="whatsapp",
    max_text=4096,
)

INSTAGRAM = Capabilities(
    name="instagram",
    lists=False,
    buttons=3,
    images=True,
    markdown="plain",
    max_text=1000,
)

MESSENGER = Capabilities(
    name="messenger",
    lists=False,
    buttons=3,
    images=True,
    markdown="plain",
    max_text=2000,
)

WEBCHAT = Capabilities(
    name="webchat",
    lists=True,
    buttons=8,
    images=True,
    markdown="markdown",
    max_text=4000,
)


@dataclass
class Inbound:
    """Mensaje que llega, ya normalizado."""

    channel: str
    external_id: str
    text: str = ""
    name: str | None = None
    media: dict | None = None
    raw: dict = field(default_factory=dict)
