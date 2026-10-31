"""Puente a lo relacionado: el cliente pide algo que no hay y se lo guía.

Ejemplo: pide «halloween», no hay, y en vez de cerrar con «no tengo», la IA
propone varias ideas (noche de películas, parrilla con amigos, decorar) y el
bot muestra productos que sí existen para cada idea.
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
from . import catalog, emoji

logger = logging.getLogger(__name__)

PROMPT = """Un cliente de un homecenter boliviano pidió «{termino}» y no está
en el catálogo.

Pensá con creatividad para qué podría querer eso y qué SÍ vende un homecenter.
Proponé 3 ideas distintas (no tres variantes de lo mismo), cada una con las
categorías o productos que la resuelven.

Respondé SOLO un JSON con esta forma:
{{"intenciones": [
  {{"idea": "frase corta de qué quería hacer", "categorias": ["...", "..."]}}
]}}

Ejemplo para «halloween»:
{{"intenciones": [
  {{"idea": "una noche de películas de terror en casa", "categorias": ["televisor", "sillón"]}},
  {{"idea": "reunión con amigos a la parrilla", "categorias": ["parrilla", "carbón"]}},
  {{"idea": "ambientar con luces y velas", "categorias": ["vela", "lámpara"]}}
]}}
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

    intenciones = datos.get("intenciones")
    if isinstance(intenciones, list):
        limpias: list[dict] = []
        for item in intenciones[:4]:
            if not isinstance(item, dict):
                continue
            idea = str(item.get("idea") or "").strip()[:120]
            categorias = item.get("categorias")
            if not isinstance(categorias, list):
                continue
            claves = [
                str(clave).strip()
                for clave in categorias
                if isinstance(clave, str)
                and 2 <= len(str(clave).strip()) <= 40
            ]
            if idea and claves:
                limpias.append({"idea": idea, "categorias": claves[:4]})
        if limpias:
            return {"intenciones": limpias}

    # Formato anterior: una sola intención y una lista de relacionadas.
    intencion = str(datos.get("intencion") or "").strip()
    relativas = datos.get("relacionadas")
    if isinstance(relativas, list):
        claves = [
            str(item).strip()
            for item in relativas
            if isinstance(item, str) and 2 <= len(str(item).strip()) <= 40
        ]
        if claves:
            return {
                "intenciones": [
                    {"idea": intencion[:120], "categorias": claves[:5]}
                ]
            }
    return None


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
            temperature=0.7,
            max_tokens=320,
            extra_body={"thinking": {"type": "disabled"}},
        )
        from . import ai_usage

        ai_usage.registrar(
            "relacionados", getattr(completado, "usage", None),
            modelo=settings.deepseek_model,
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
) -> tuple[list[str], list]:
    """Ideas y un producto existente por idea."""
    from ..agent import _liberar_transaccion

    await _liberar_transaccion(session)
    lectura = await _pedir_a_la_ia(termino)
    if not lectura:
        return [], []

    ideas: list[str] = []
    productos: list = []
    vistos: set[str] = set()
    for intencion in lectura["intenciones"]:
        elegido = None
        for clave in intencion["categorias"]:
            filas = await catalog.search_items(session, clave, limit=3)
            for item in filas:
                if item.sku in vistos:
                    continue
                elegido = item
                break
            if elegido is not None:
                break
        if elegido is None:
            continue
        vistos.add(elegido.sku)
        productos.append(elegido)
        ideas.append(intencion["idea"])
        if len(productos) >= limite:
            break
    return ideas, productos


async def reply(
    agent, session: AsyncSession, contact: Contact, termino: str
) -> AgentReply | None:
    """Respuesta que reconoce el faltante y propone varias ideas."""
    from ..agent import Toolbox
    from . import missing

    termino = re.sub(
        r"^(hola|buenas|buen día|buenas tardes)\s+", "", termino.strip().lower()
    )
    termino = re.sub(r"^(vendes|vende|tienen|tiene|hay)\s+", "", termino)
    termino = termino.strip(" ?!.")
    if not termino:
        return None

    # Primero la familia del producto: un monitor se parece a un televisor,
    # no a "vigilar la casa". Las ideas libres quedan como último recurso.
    from . import familia

    afin, afines = await familia.buscar(session, termino)
    if afines:
        from . import product_view

        tarjetas_afines = [product_view.payload(fila) for fila in afines[:3]]
        toolbox_afin = Toolbox(session, contact, agent.wa)
        await toolbox_afin._attach_promotions(tarjetas_afines)
        agent._trace(f"Faltante {termino}: familia {afin}")
        return AgentReply(
            [
                Outbound(
                    text=(
                        f"No tengo *{termino}* 🛍️ Pero esto es lo más parecido "
                        f"que tenemos ({afin}):"
                    )
                ),
                *agent._search_cards(tarjetas_afines),
            ]
        )

    ideas, productos = await relacionadas(session, termino)
    if not productos:
        return None

    from . import rule_apply

    productos = await rule_apply.aplicar(
        session, termino, productos, categoria=termino
    )
    toolbox = Toolbox(session, contact, agent.wa)
    tarjetas = [Toolbox._product(item) for item in productos]
    await toolbox._attach_promotions(tarjetas)

    icono = emoji.para(termino)
    if len(ideas) >= 2:
        lista = ", ".join(ideas[:-1]) + f" o {ideas[-1]}"
        puente = (
            f"*{termino.capitalize()}* no tengo {icono} Pero para algo así se "
            f"me ocurren varias ideas: {lista}. Mirá lo que sí tengo:"
        )
    elif ideas:
        puente = (
            f"*{termino.capitalize()}* no tengo {icono} Pero si la idea es "
            f"{ideas[0]}, mirá esto:"
        )
    else:
        puente = f"*{termino.capitalize()}* no tengo {icono} Mirá esto:"

    await missing.record(
        session,
        termino,
        intent="; ".join(ideas)[:200],
        related=[item.name for item in productos],
        answered=True,
    )
    agent._trace(f"Relacionado con {termino}: {'; '.join(ideas)}")
    respuesta = AgentReply(
        [
            Outbound(text=puente),
            *agent._search_cards(tarjetas),
        ]
    )
    return await rule_apply.anexar_preguntas(
        session, termino, respuesta, categoria=termino
    )


async def leer_intenciones(
    session: AsyncSession, termino: str
) -> list[dict]:
    """Ideas para una ocasión, con sus categorías (sin buscar productos)."""
    lectura = await _pedir_a_la_ia(termino)
    return list((lectura or {}).get("intenciones") or [])
