"""Ideas para una ocasión: el bot pregunta antes de mostrar productos.

Cuando el pedido es una ocasión («algo para Halloween») y hay varias
intenciones posibles, el bot ofrece las ideas en botones. Al elegir una,
busca las categorías de esa idea.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact
from ..replies import AgentReply
from ..whatsapp import Outbound
from . import catalog, emoji

logger = logging.getLogger(__name__)


def _clave(texto: str) -> str:
    base = re.sub(r"[^a-záéíóúñ ]", "", (texto or "").lower()).strip()
    return base.replace(" ", "-")[:24]


def botones(ideas: list[dict]) -> list[dict]:
    """Hasta 3 botones; cada uno lleva sus categorías en el id."""
    salida: list[dict] = []
    for idea in ideas[:3]:
        etiqueta = (idea.get("idea") or "Opción").strip()
        titulo = etiqueta if len(etiqueta) <= 20 else etiqueta[:19] + "…"
        datos = json.dumps(
            {"i": idea.get("idea"), "c": idea.get("categorias")[:4]},
            ensure_ascii=False,
        )
        salida.append({"id": f"idea:{datos}", "title": titulo})
    return salida


def leer(texto: str) -> dict | None:
    """Interpreta el id de un botón de idea."""
    try:
        return json.loads((texto or "").split(":", 1)[1])
    except (IndexError, json.JSONDecodeError):
        return None


async def preguntar(
    session: AsyncSession, termino: str, ideas: list[dict]
) -> AgentReply | None:
    """Pregunta cuál de las ideas le interesa."""
    if len(ideas) < 2:
        return None
    icono = emoji.para(termino)
    nombres = [idea["idea"] for idea in ideas[:3]]
    listado = ", ".join(nombres[:-1]) + f" o {nombres[-1]}"
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=(
                    f"*{termino.capitalize()}* como tal no tengo {icono} "
                    f"Pero se me ocurren varias ideas: {listado}.\n\n"
                    "¿Cuál te interesa? Te muestro opciones de esa 👇"
                ),
                buttons=botones(ideas),
            )
        ]
    )


async def responder_idea(
    session: AsyncSession, contacto: Contact, raw: str, agent
) -> AgentReply | None:
    """Busca los productos de la idea elegida."""
    from ..agent import Toolbox

    datos = leer(raw)
    if not datos:
        return None
    ideas_categorias = datos.get("c") or []
    idea = str(datos.get("i") or "")
    productos: list[dict] = []
    vistos: set[str] = set()
    for clave in ideas_categorias:
        filas = await catalog.search_items(session, clave, limit=3)
        for item in filas:
            if item.sku in vistos:
                continue
            vistos.add(item.sku)
            productos.append(item)
    if not productos:
        return None
    from . import rule_apply

    productos = await rule_apply.aplicar(
        session, " ".join(ideas_categorias), productos, categoria=idea
    )
    toolbox = Toolbox(session, contacto, agent.wa)
    tarjetas = [Toolbox._product(item) for item in productos[:5]]
    await toolbox._attach_promotions(tarjetas)
    agent._trace(f"Idea elegida: {idea}")
    return AgentReply(
        [
            Outbound(text=f"Para *{idea}* tengo esto {emoji.para(idea)}:"),
            *agent._search_cards(tarjetas),
        ]
    )
