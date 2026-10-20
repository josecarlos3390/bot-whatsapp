"""Memoria de cliente: perfil, hechos y resumen de conversación."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal
from ..models import (
    Contact,
    Conversation,
    ConversationSummary,
    CustomerFact,
    CustomerProfile,
    Message,
)
from . import customers, purchases
from . import feedback as feedback_service
from .customer_analysis import analysis_text

logger = logging.getLogger(__name__)

ALLOWED_FACTS = {
    "ciudad",
    "zona",
    "tienda_preferida",
    "ocasion",
    "presupuesto",
    "estilo",
    "color",
    "talla",
    "categoria_favorita",
    "marca_favorita",
    "tiene_mascota",
    "tipo_vivienda",
    "no_contactar",
    "nota",
}

SENSITIVE_MARKERS = ("carnet", "cedula", "ci ", "tarjeta", "cvv", "password")


def _clean(value: str, limit: int = 300) -> str:
    return (value or "").strip()[:limit]


async def get_profile(
    session: AsyncSession, contact_id: str
) -> CustomerProfile | None:
    return await session.scalar(
        select(CustomerProfile).where(CustomerProfile.contact_id == contact_id)
    )


async def get_facts(
    session: AsyncSession, contact_id: str
) -> list[CustomerFact]:
    return list(
        (
            await session.scalars(
                select(CustomerFact)
                .where(CustomerFact.contact_id == contact_id)
                .order_by(CustomerFact.key)
            )
        ).all()
    )


async def get_summary(
    session: AsyncSession, conversation_id: str
) -> ConversationSummary | None:
    return await session.scalar(
        select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id
        )
    )


async def memory_text(
    session: AsyncSession, contact: Contact, conversation_id: str
) -> str:
    profile = await get_profile(session, contact.id)
    facts = await get_facts(session, contact.id)
    summary = await get_summary(session, conversation_id)
    parts: list[str] = []
    if contact.name:
        parts.append(f"Nombre: {contact.name}")
    if profile:
        if profile.city:
            parts.append(f"Ciudad: {profile.city}")
        if profile.preferred_store:
            parts.append(f"Tienda preferida: {profile.preferred_store}")
        if profile.preferences:
            parts.append(
                "Preferencias: "
                + ", ".join(f"{k}={v}" for k, v in profile.preferences.items())
            )
    if facts:
        parts.append(
            "Datos recordados: "
            + "; ".join(f"{fact.key}={fact.value}" for fact in facts)
        )
    if summary and summary.summary:
        parts.append(f"Resumen de conversaciones previas: {summary.summary}")
    purchase_text = await purchases.history_text(session, contact.id)
    if purchase_text:
        parts.append(purchase_text)
    customer_text = await analysis_text(session, contact.id)
    if customer_text:
        parts.append(customer_text)
    feedback_prompt = await feedback_service.due_feedback_prompt(
        session, contact.id
    )
    if feedback_prompt:
        parts.append(feedback_prompt)
    candidate = await customers.pending_candidate(session, contact.id)
    if candidate:
        parts.append(
            "Identificación pendiente: "
            f"{candidate.name_masked or candidate.name} "
            f"(CardCode {candidate.card_code}). "
            "Si el cliente confirma que es él, usá link_customer."
        )
    return "\n".join(parts)


async def remember_fact(
    session: AsyncSession,
    contact_id: str,
    key: str,
    value: str,
    *,
    consent: bool,
    source: str = "whatsapp",
) -> CustomerFact:
    key = _clean(key, 60).lower().replace(" ", "_")
    value = _clean(value)
    if not consent:
        raise ValueError(
            "Para guardar un dato necesitas el consentimiento explícito del cliente."
        )
    if key not in ALLOWED_FACTS:
        raise ValueError(f"Dato no permitido: {key}")
    if any(marker in value.lower() for marker in SENSITIVE_MARKERS):
        raise ValueError("No se guardan datos sensibles en la memoria comercial.")

    profile = await get_profile(session, contact_id)
    if profile is None:
        profile = CustomerProfile(contact_id=contact_id)
        session.add(profile)
    if profile.consent_at is None:
        profile.consent_at = datetime.now(timezone.utc)
    if key == "ciudad":
        profile.city = value[:80]
    elif key == "tienda_preferida":
        profile.preferred_store = value[:20]

    fact = await session.scalar(
        select(CustomerFact).where(
            CustomerFact.contact_id == contact_id, CustomerFact.key == key
        )
    )
    if fact is None:
        fact = CustomerFact(
            contact_id=contact_id,
            key=key,
            value=value,
            source=source,
        )
        session.add(fact)
    else:
        fact.value = value
        fact.source = source
    await session.commit()
    return fact


async def update_profile(
    session: AsyncSession,
    contact_id: str,
    *,
    city: str | None = None,
    preferred_store: str | None = None,
    preferences: dict[str, Any] | None = None,
    consent: bool = False,
) -> CustomerProfile:
    if not consent:
        raise ValueError("Se requiere consentimiento para guardar el perfil.")
    profile = await get_profile(session, contact_id)
    if profile is None:
        profile = CustomerProfile(contact_id=contact_id)
        session.add(profile)
    if city:
        profile.city = _clean(city, 80)
    if preferred_store:
        profile.preferred_store = _clean(preferred_store, 20)
    if preferences:
        profile.preferences = {**profile.preferences, **preferences}
    if profile.consent_at is None:
        profile.consent_at = datetime.now(timezone.utc)
    await session.commit()
    return profile


async def summarize_conversation(conversation_id: str) -> None:
    if not settings.deepseek_api_key:
        return
    async with SessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            return
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(40)
            )
        ).all()
        if len(rows) < 6:
            return
        total_messages = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        transcript = "\n".join(
            f"{'Cliente' if row.direction == 'in' else 'Bot'}: {row.text}"
            for row in reversed(rows)
            if row.text
        )
        client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        try:
            completion = await client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Resume la conversación en máximo 4 líneas. "
                            "Incluye necesidad, objeciones, productos vistos, "
                            "tienda/presupuesto y estado. No inventes datos."
                        ),
                    },
                    {"role": "user", "content": transcript[-6000:]},
                ],
                temperature=0.2,
                max_tokens=220,
                extra_body={"thinking": {"type": "disabled"}},
            )
            summary_text = (completion.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001 - el resumen no debe romper el bot
            logger.exception("No se pudo resumir la conversación %s", conversation_id)
            return
        finally:
            await client.close()

        if not summary_text:
            return
        summary = await get_summary(session, conversation_id)
        if summary is None:
            summary = ConversationSummary(
                conversation_id=conversation_id,
                summary=summary_text,
                message_count=int(total_messages or len(rows)),
            )
            session.add(summary)
        else:
            summary.summary = summary_text
            summary.message_count = int(total_messages or len(rows))
        await session.commit()


_tasks: set[asyncio.Task] = set()


async def maybe_schedule_summary(conversation_id: str) -> None:
    if not settings.memory_auto_summary:
        return
    async with SessionLocal() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        summary = await get_summary(session, conversation_id)
        previous = summary.message_count if summary else 0
        if (total or 0) < 6 or (total or 0) - previous < 8:
            return

    if settings.queue_enabled:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(
                RedisSettings.from_dsn(settings.redis_url)
            )
            try:
                await pool.enqueue_job(
                    "summarize_conversation_job", conversation_id
                )
            finally:
                await pool.aclose()
            return
        except Exception:  # noqa: BLE001 - fallback local
            logger.exception(
                "No se pudo encolar el resumen; se ejecuta en segundo plano"
            )

    task = asyncio.create_task(summarize_conversation(conversation_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
