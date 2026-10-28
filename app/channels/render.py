"""Traducción de lo que arma el bot al formato que cada canal entiende.

El caso delicado: WhatsApp permite listas y Messenger/Instagram no. Acá se
convierten en texto numerado (o en botones si alcanzan) sin perder la
información, para que la conversación siga guiando igual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .base import Capabilities

_INDICE = re.compile(r"^\s*(\d+)\.\s", re.MULTILINE)


@dataclass
class Rendered:
    """Mensaje listo para enviar por un canal."""

    kind: str = "text"  # text | image | buttons | list
    text: str = ""
    buttons: list[dict] = field(default_factory=list)
    image_url: str = ""
    rows: list[dict] = field(default_factory=list)


def _texto(mensaje, capabilities: Capabilities) -> str:
    texto = mensaje.text or ""
    if capabilities.markdown == "plain":
        # Instagram y Messenger muestran los asteriscos tal cual.
        texto = re.sub(r"\*([^*\n]+)\*", r"\1", texto)
        texto = re.sub(r"_([^_\n]+)_", r"\1", texto)
    if len(texto) > capabilities.max_text:
        texto = texto[: capabilities.max_text - 1].rstrip() + "…"
    return texto


def _botones(mensaje, capabilities: Capabilities) -> tuple[list[dict], str]:
    """Botones que entran y, si sobran, el texto con las opciones."""
    botones = list(mensaje.buttons or [])
    if capabilities.buttons <= 0:
        if not botones:
            return [], ""
        lineas = [f"{i}. {b['title']}" for i, b in enumerate(botones, start=1)]
        return [], "\n".join(lineas)
    if len(botones) <= capabilities.buttons:
        return botones, ""
    entran = botones[: capabilities.buttons]
    resto = botones[capabilities.buttons :]
    lineas = [f"{i}. {b['title']}" for i, b in enumerate(resto, start=1)]
    return entran, "\n".join(lineas)


def _filas_a_texto(filas: list[dict]) -> str:
    """Lista de WhatsApp convertida en opciones numeradas."""
    lineas = []
    for indice, fila in enumerate(filas, start=1):
        titulo = (fila.get("title") or "").strip()
        detalle = (fila.get("description") or "").strip()
        lineas.append(f"{indice}. {titulo}" + (f" — {detalle}" if detalle else ""))
    return "\n".join(lineas)


def render(mensaje, capabilities: Capabilities) -> list[Rendered]:
    """Convierte un mensaje del bot a lo que el canal puede mostrar."""
    kind = getattr(mensaje, "kind", "text") or "text"
    texto = _texto(mensaje, capabilities)
    salida: list[Rendered] = []

    if kind == "image":
        url = getattr(mensaje, "url", "") or ""
        if capabilities.images and url:
            salida.append(Rendered(kind="image", text=texto, image_url=url))
        elif texto:
            salida.append(Rendered(kind="text", text=texto))
        return salida

    if kind == "list":
        filas = [
            fila
            for seccion in (mensaje.sections or [])
            for fila in (seccion.get("rows") or [])
        ]
        if capabilities.lists:
            salida.append(
                Rendered(
                    kind="list",
                    text=texto,
                    rows=filas,
                    buttons=[{"title": getattr(mensaje, "button_text", "Ver")}],
                )
            )
            return salida
        # Sin listas: las opciones van como texto numerado.
        opciones = _filas_a_texto(filas)
        cuerpo = "\n\n".join(parte for parte in (texto, opciones) if parte)
        if filas:
            cuerpo += "\n\nRespondé con el número de la opción."
        salida.append(Rendered(kind="text", text=cuerpo))
        return salida

    if kind in {"buttons", "cta"}:
        botones, sobrantes = _botones(mensaje, capabilities)
        cuerpo = "\n\n".join(
            parte for parte in (texto, sobrantes) if parte
        )
        if botones:
            salida.append(
                Rendered(kind="buttons", text=cuerpo, buttons=botones)
            )
        else:
            salida.append(Rendered(kind="text", text=cuerpo))
        return salida

    if texto:
        salida.append(Rendered(kind="text", text=texto))
    return salida


def render_reply(reply, capabilities: Capabilities) -> list[Rendered]:
    """Traduce una respuesta completa del agente."""
    salida: list[Rendered] = []
    for mensaje in getattr(reply, "messages", []) or []:
        salida.extend(render(mensaje, capabilities))
    return salida
