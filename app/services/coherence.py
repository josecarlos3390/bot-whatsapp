"""Guard de coherencia: la respuesta no puede hablar de algo que nadie dijo.

Ejemplo real: el cliente pidió "algo para halloween" y el bot respondió
"¿te vas de viaje o te quedás? te armo un plan de películas". La respuesta
introducía un contexto que no existía en la charla.

El guard compara los temas "de contexto" de la respuesta con lo que se habló
en los últimos mensajes. Si la respuesta inventa un tema, se descarta.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, Message

# Temas que solo tienen sentido si el cliente los mencionó antes.
TEMAS_CONTEXTO = (
    "viaje", "viajar", "vacacion", "vacaciones", "playa", "hotel",
    "pelicula", "películas", "cine", "boda", "casamiento", "bebe", "bebé",
    "embarazo", "mudanza", "cumpleaños", "aniversario", "navidad",
    "halloween", "regalo", "regalar", "estudio", "oficina", "jardin",
    "jardín", "terraza", "pileta", "piscina",
)

_VENTANA = 8


def _tokens(texto: str) -> set[str]:
    return set(re.findall(r"[a-záéíóúñü]{4,}", (texto or "").lower()))


def temas_inventados(respuesta: str, contexto: str) -> list[str]:
    """Temas de la respuesta que no aparecen en la conversación."""
    propios = _tokens(respuesta)
    hablados = _tokens(contexto)
    inventados = []
    for tema in TEMAS_CONTEXTO:
        if tema in propios and tema not in hablados:
            inventados.append(tema)
    return inventados


async def contexto_reciente(
    session: AsyncSession, contact: Contact, extra: str = "", limite: int = _VENTANA
) -> str:
    """Últimos mensajes (cliente y bot) más el mensaje actual."""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return extra
    filas = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversacion.id)
            .order_by(Message.created_at.desc())
            .limit(limite)
        )
    ).all()
    partes = [fila.text or "" for fila in reversed(filas)]
    partes.append(extra or "")
    return " ".join(partes)
