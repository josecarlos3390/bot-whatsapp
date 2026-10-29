"""Puente a lo relacionado: el cliente pide algo que no hay y se lo guía.

Ejemplo: pide «pelotas», no hay, y en vez de cerrar con «no tengo», la IA
propone la intención (jugar, ver fútbol con amigos) y el bot muestra
productos que sí existen y encajan con esa intención.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact
from ..replies import AgentReply
from ..whatsapp import Outbound
from . import catalog

logger = logging.getLogger(__name__)

PROMPT = """Un cliente de un homecenter boliviano pidió «{termino}» y no está
en el catálogo.

Respondé SOLO un JSON con esta forma:
{{"intencion": "qué quería hacer realmente, en menos de 12 palabras",
  "relacionadas": ["3 a 5 categorías o productos que SÍ vende un homecenter
y se relacionan con esa intención"]}}

Ejemplo: para «pelotas» → {{"intencion": "jugar o ver fútbol con amigos",
  "relacionadas": ["televisor", "sillón", "parrilla"]}}
No inventes marcas ni precios."""


def _limpiar(texto: str) -> str:
    return (texto or "").strip().strip("`").strip()


def parsear(respuesta: str) -> dict | None:
    """Interpreta la respuesta del modelo (tolera texto alrededor del JSON)."""
    texto = _limpiar(respuesta)
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        datos = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, dict):
        return None
    intencion = str(datos.get("intencion") or "").strip()
    relativas = datos.get("relacionadas")
    if not isinstance(relativas, list):
        return None
    limpio = [
        str(item).strip()
        for item in relativas
        if isinstance(item, str) and 2 <= len(str(item).strip()) <= 40
    ]
    if not limpio:
        return None
    return {"intencion": intencion[:120], "relacionadas": limpio[:5]}


async def _pedir_a_la_ia(termino: str) -> dict | None:
    from openai import AsyncOpenAI

    cliente = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    try:
        completado = await cliente.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "user", "content": PROMPT.format(termino=termino)}
            ],
            temperature=0.4,
            max_tokens=220,
            extra_body={"thinking": {"type": "disabled"}},
        )
        contenido = completado.choices[0].message.content or ""
    except Exception:  # noqa: BLE001 - sin IA se sigue con el mensaje normal
        logger.debug("No se pudo pedir relacionadas", exc_info=True)
        return None
    finally:
        await cliente.close()
    return parsear(contenido)


async def relacionadas(
    session: AsyncSession, termino: str, limite: int = 3
) -> tuple[str, list]:
    """Intención y productos que sí existen para esa intención."""
    lectura = await _pedir_a_la_ia(termino)
    if not lectura:
        return "", []

    vistos: set[str] = set()
    productos: list = []
    for clave in lectura["relacionadas"]:
        filas = await catalog.search_items(session, clave, limit=3)
        for item in filas:
            if item.sku in vistos:
                continue
            vistos.add(item.sku)
            productos.append(item)
            if len(productos) >= limite:
                break
        if len(productos) >= limite:
            break
    return lectura["intencion"], productos


async def reply(
    agent, session: AsyncSession, contact: Contact, termino: str
) -> AgentReply | None:
    """Respuesta que reconoce el faltante y guía a lo relacionado."""
    from ..agent import Toolbox

    termino = re.sub(r"^(hola|buenas|buen día|buenas tardes)\s+", "", termino.strip().lower())
    termino = re.sub(r"^(vendes|vende|tienen|tiene|hay)\s+", "", termino).strip(" ?!.")
    if not termino:
        return None

    intencion, productos = await relacionadas(session, termino)
    if not productos:
        return None

    toolbox = Toolbox(session, contact, agent.wa)
    tarjetas = [Toolbox._product(item) for item in productos]
    await toolbox._attach_promotions(tarjetas)

    puente = (
        f"*{termino.capitalize()}* no tengo 😕"
        if not intencion
        else f"*{termino.capitalize()}* no tengo 😕 Pero si la idea es "
        f"{intencion}, mirá esto:"
    )
    agent._trace(f"Relacionado con {termino}: {intencion or 'sin intención'}")
    return AgentReply(
        [
            Outbound(text=puente),
            *agent._search_cards(tarjetas),
        ]
    )
