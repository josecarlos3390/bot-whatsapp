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
        f"{saludo}ya te pasé lo que tengo sobre eso. Si necesitás confirmar "
        "un dato puntual (precio final, stock o plazo), te paso con un asesor "
        "para que te lo confirme."
    )


def _parecido(a: str, b: str, umbral: float = 0.75) -> bool:
    """Similitud de texto (0 a 1) por difflib."""
    from difflib import SequenceMatcher

    uno, otro = _normalizar(a), _normalizar(b)
    if not uno or not otro:
        return False
    return SequenceMatcher(None, uno, otro).ratio() >= umbral


async def cliente_repite(
    session: AsyncSession, contact: Contact, texto: str, limite: int = 6
) -> bool:
    """¿El cliente ya preguntó lo mismo en los mensajes anteriores?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    filas = (
        await session.scalars(
            select(Message.text)
            .where(
                Message.conversation_id == conversacion.id,
                Message.direction == "in",
                Message.text.is_not(None),
            )
            .order_by(Message.created_at.desc())
            .limit(limite + 1)
        )
    ).all()
    # La primera es el mensaje actual (ya guardado antes de responder).
    anteriores = list(filas[1:]) if filas else []
    return any(_parecido(texto or "", previo or "") for previo in anteriores)


async def respuesta_parecida(
    session: AsyncSession, contact: Contact, answer: str
) -> bool:
    """¿La respuesta se parece a la anterior (no idéntica)?"""
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
    return bool(ultimo) and _parecido(ultimo or "", answer or "")


def cambio_de_enfoque(contact: Contact) -> str:
    """Mensaje cuando el cliente insiste y el bot iba a repetir."""
    nombre = (contact.name or "").split(" ")[0]
    saludo = f"{nombre}, " if nombre else ""
    return (
        f"{saludo}entiendo que lo que te mostré no te sirvió. Para no "
        "repetirte la misma información: decime qué te falta (medida, marca "
        "o presupuesto) y lo busco de nuevo, o te paso con un asesor que lo "
        "revise con vos."
    )
