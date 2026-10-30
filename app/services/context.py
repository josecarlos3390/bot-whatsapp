"""Contexto de la charla: el rubro no se pierde con una respuesta suelta."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, Message
from . import conversation_state

# Respuestas típicas a una pregunta del bot ("¿para casa o profesional?").
_RESPUESTA = re.compile(
    r"^(para|es para|uso|lo quiero para|seria para|sería para|ok|si|sí)\b"
)


def es_respuesta_suelta(texto: str) -> bool:
    """¿Es una respuesta corta a una pregunta y no un rubro nuevo?"""
    valor = (texto or "").strip().lower()
    if not valor:
        return False
    if len(valor.split()) > 4:
        return False
    return bool(_RESPUESTA.match(valor))


async def ultimo_texto_entrante(
    session: AsyncSession, contact_id: str
) -> str:
    """Último mensaje del cliente."""
    fila = await session.scalar(
        select(Message.text)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.contact_id == contact_id,
            Message.direction == "in",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return fila or ""


async def rubro(session: AsyncSession, contact: Contact) -> str:
    """Rubro vigente de la charla (estado o última consulta)."""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return ""
    estado = await conversation_state.get_state(session, conversacion.id)
    return (getattr(estado, "category", None) or "") or (
        conversacion.last_query or ""
    )


async def es_respuesta_suelta_de(
    session: AsyncSession, contact_id: str
) -> bool:
    """¿El último mensaje del cliente es una respuesta corta?"""
    return es_respuesta_suelta(await ultimo_texto_entrante(session, contact_id))
