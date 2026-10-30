"""Preguntar el uso antes de listar: la clave para acertar.

«Quiero productos de tecnología» es una puerta abierta. Un vendedor pregunta
para qué lo necesita antes de mostrar el catálogo. Acá se detecta ese momento
y se ofrecen 2 o 3 usos concretos; al elegir, se busca con esa información.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, Conversation
from ..replies import AgentReply
from ..whatsapp import Outbound

logger = logging.getLogger(__name__)

PROMPT = """En un homecenter, un cliente escribe: «{texto}».

¿Alcanza para recomendar un producto concreto o falta saber el uso?
Si falta, escribí una pregunta corta y 3 usos posibles (cada uno con la
búsqueda concreta que habría que hacer).

Respondé SOLO JSON:
{{"preguntar": true, "pregunta": "¿...?",
  "opciones": [{{"titulo": "máx 20 caracteres", "consulta": "búsqueda"}}]}}

Si el mensaje ya dice el uso o el producto exacto, respondé
{{"preguntar": false}}.
No inventes productos."""


def parsear(respuesta: str) -> dict | None:
    texto = (respuesta or "").strip().strip("`")
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        datos = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, dict) or not datos.get("preguntar"):
        return None
    pregunta = str(datos.get("pregunta") or "").strip()[:200]
    opciones = datos.get("opciones")
    if not pregunta or not isinstance(opciones, list):
        return None
    limpias = []
    for opcion in opciones[:3]:
        if not isinstance(opcion, dict):
            continue
        titulo = str(opcion.get("titulo") or "").strip()[:20]
        consulta = str(opcion.get("consulta") or "").strip()[:80]
        if titulo and consulta:
            limpias.append({"titulo": titulo, "consulta": consulta})
    if len(limpias) < 2:
        return None
    return {"pregunta": pregunta, "opciones": limpias}


async def _pedir_a_la_ia(agent, texto: str) -> dict | None:
    # Se usa el mismo cliente que el agente: así los tests y el modo demo
    # funcionan sin llamar a la red.
    cliente = agent._llm()
    try:
        completado = await cliente.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "user", "content": PROMPT.format(texto=texto)}
            ],
            temperature=0.3,
            max_tokens=220,
            extra_body={"thinking": {"type": "disabled"}},
        )
        contenido = completado.choices[0].message.content or ""
    except Exception:  # noqa: BLE001 - sin IA se responde normal
        logger.debug("No se pudo evaluar la claridad del pedido", exc_info=True)
        return None
    finally:
        pass
    return parsear(contenido)


# Palabras que abren el pedido sin decir qué se busca.
GENERICOS = (
    "productos",
    "algo",
    "cosas",
    "opciones",
    "recomendame",
    "recomiendame",
    "que tienen",
    "que hay",
    "que venden",
    "surtido",
)


def es_amplio(texto: str) -> bool:
    """¿El pedido abre sin decir qué necesita? (filtro barato, sin IA)"""
    valor = (texto or "").strip().lower()
    if not valor:
        return False
    if len(valor.split()) > 7:
        return False
    return any(palabra in valor for palabra in GENERICOS)


async def preguntar(
    agent, session: AsyncSession, contact: Contact, raw: str
) -> AgentReply | None:
    """Pregunta el uso, si el pedido es demasiado abierto."""
    if not settings.deepseek_api_key:
        return None
    # Filtro barato: si el pedido nombra algo concreto, no se pregunta.
    if not es_amplio(raw):
        return None
    # Solo la primera búsqueda de la charla: después ya hay contexto y
    # preguntar de nuevo molesta.
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is not None and conversacion.last_query:
        return None

    from ..agent import _liberar_transaccion

    await _liberar_transaccion(session)
    lectura = await _pedir_a_la_ia(agent, raw)
    if not lectura:
        return None

    agent._trace(f"Pregunta de uso: {lectura['pregunta']}")
    if conversacion is not None:
        conversacion.last_query = raw[:300]
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=lectura["pregunta"],
                buttons=[
                    {
                        "id": f"uso:{opcion['consulta']}",
                        "title": opcion["titulo"],
                    }
                    for opcion in lectura["opciones"]
                ],
            )
        ]
    )
