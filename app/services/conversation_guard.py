"""Guarda de conversación: pregunta pendiente y control de repetición."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, ConversationGuard


SLOT_PATTERNS = (
    ("size", re.compile(r"\b(medida|pulgadas?|plazas?|tamaño)\b", re.I)),
    ("budget", re.compile(r"\b(presupuesto|precio|cu[aá]nto quer[eé]s gastar)\b", re.I)),
    ("quantity", re.compile(r"\b(cantidad|cu[aá]ntas? unidades)\b", re.I)),
    ("brand", re.compile(r"\b(marca|preferencia de marca)\b", re.I)),
    ("topic", re.compile(r"\b(qu[eé] tipo|qu[eé] clase|para qu[eé]|qu[eé] te interesa|qu[eé] busc[aá]s)\b", re.I)),
)


async def _conversation(
    session: AsyncSession, contact: Contact
) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )


async def get_for_contact(
    session: AsyncSession, contact: Contact
) -> ConversationGuard | None:
    conversation = await _conversation(session, contact)
    if conversation is None:
        return None
    return await session.scalar(
        select(ConversationGuard).where(
            ConversationGuard.conversation_id == conversation.id
        )
    )


async def _get_or_create(
    session: AsyncSession, contact: Contact
) -> ConversationGuard | None:
    conversation = await _conversation(session, contact)
    if conversation is None:
        return None
    guard = await session.scalar(
        select(ConversationGuard).where(
            ConversationGuard.conversation_id == conversation.id
        )
    )
    if guard is None:
        guard = ConversationGuard(conversation_id=conversation.id)
        session.add(guard)
        await session.flush()
    return guard


async def set_pending(
    session: AsyncSession,
    contact: Contact,
    *,
    slot: str,
    question: str,
    query: str | None,
) -> None:
    guard = await _get_or_create(session, contact)
    if guard is None:
        return
    guard.pending_slot = slot
    guard.pending_question = question[:500]
    guard.pending_query = (query or "")[:200] or None
    await session.commit()


async def clear_pending(session: AsyncSession, contact: Contact) -> None:
    guard = await get_for_contact(session, contact)
    if guard is None:
        return
    guard.pending_slot = None
    guard.pending_question = None
    guard.pending_query = None
    await session.commit()


def detect_slot(answer: str | None) -> tuple[str, str] | None:
    text = answer or ""
    if "?" not in text and "¿" not in text:
        return None
    for slot, pattern in SLOT_PATTERNS:
        if pattern.search(text):
            return slot, text
    return None


async def record_answer(
    session: AsyncSession,
    contact: Contact,
    *,
    user_text: str,
    answer: str,
) -> bool:
    """Devuelve True si la respuesta se repite demasiadas veces."""
    guard = await _get_or_create(session, contact)
    if guard is None:
        return False
    slot = detect_slot(answer)
    if slot:
        guard.pending_slot, guard.pending_question = slot[0], slot[1][:500]
        guard.pending_query = user_text[:200]
    else:
        guard.pending_slot = None
        guard.pending_question = None
        guard.pending_query = None
    normalized = re.sub(r"\s+", " ", (answer or "").strip().lower())
    previous = re.sub(
        r"\s+", " ", (guard.last_answer or "").strip().lower()
    )
    if normalized and normalized == previous:
        guard.repeat_count += 1
    else:
        guard.repeat_count = 0
    guard.last_answer = (answer or "")[:1000]
    await session.commit()
    return guard.repeat_count >= 1


def fallback_text() -> str:
    return (
        "No te entendí del todo. ¿Buscás un producto, hacer seguimiento de "
        "un pedido o preferís que te derive con un asesor?"
    )


def loop_text() -> str:
    return (
        "No quiero repetirte lo mismo. ¿Lo vemos de otra forma, te muestro "
        "otras opciones o te derivo con un asesor?"
    )
