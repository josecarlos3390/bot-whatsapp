"""No repetir exactamente la misma respuesta que ya se envió.

El fuzzing encontró que, ante un cliente enojado, el bot podía contestar dos
veces el mismo texto. La detección de bucles miraba el historial del guard;
esto lo cubre en la salida, sin importar qué camino generó la respuesta.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, Message


def _normalizar(texto: str) -> str:
    limpio = re.sub(r"\s+", " ", (texto or "").strip().lower())
    return limpio[:400]


async def repetida(
    session: AsyncSession, contact: Contact, answer: str
) -> bool:
    """¿La respuesta es igual a la última que se envió?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    ultimo = await session.scalar(
        select(Message.text)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "out",
            Message.text.is_not(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if not ultimo:
        return False
    return _normalizar(ultimo) == _normalizar(answer) and len(_normalizar(ultimo)) > 20


def variante(contact: Contact) -> str:
    """Respuesta distinta para no repetir el mismo texto."""
    nombre = (contact.name or "").split(" ")[0]
    saludo = f"{nombre}, " if nombre else ""
    return (
        f"{saludo}seguimos con tu caso. Para no repetirte lo mismo: "
        "¿preferís que te pase con un asesor o que te muestre otra cosa "
        "mientras tanto?"
    )
