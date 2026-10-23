"""Flujo de devolución guiado por reglas de calidad."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaRule, Contact, Conversation, ConversationFlow


def _fold(value: str | None) -> str:
    value = (value or "").strip().lower()
    return re.sub(r"\s+", " ", value)


def _yes_no(value: str) -> bool | None:
    text = _fold(value)
    if re.search(r"\b(si|sí|claro|obvio|correcto|tengo|yes)\b", text):
        return True
    if re.search(r"\b(no|nunca|negativo|no tengo|no sé|no se)\b", text):
        return False
    return None


async def get_active(
    session: AsyncSession, contact: Contact
) -> ConversationFlow | None:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversation is None:
        return None
    flow = await session.scalar(
        select(ConversationFlow).where(
            ConversationFlow.conversation_id == conversation.id,
            ConversationFlow.flow == "devolucion",
            ConversationFlow.status == "active",
        )
    )
    return flow


async def _conversation(
    session: AsyncSession, contact: Contact
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversation is None:
        conversation = Conversation(contact_id=contact.id)
        session.add(conversation)
        await session.flush()
    return conversation


def _questions(rule: AreaRule) -> list[dict]:
    return [
        question
        for question in (rule.action or {}).get("questions") or []
        if isinstance(question, dict) and question.get("text")
    ]


async def start(
    session: AsyncSession, contact: Contact, rule: AreaRule
) -> str:
    questions = _questions(rule)
    conversation = await _conversation(session, contact)
    flow = await session.scalar(
        select(ConversationFlow).where(
            ConversationFlow.conversation_id == conversation.id
        )
    )
    if flow is None:
        flow = ConversationFlow(conversation_id=conversation.id)
        session.add(flow)
    flow.flow = "devolucion"
    flow.step = 0
    flow.answers = {"_rule_id": rule.id}
    flow.status = "active"
    await session.commit()
    return (
        "Lamento lo ocurrido. Para iniciar la devolución te hago "
        f"{len(questions)} preguntas. "
        f"(1/{len(questions)}) {questions[0]['text']}"
    )


async def answer(
    session: AsyncSession, flow: ConversationFlow, text: str
) -> dict:
    rule_id = (flow.answers or {}).get("_rule_id")
    rule = await session.get(AreaRule, rule_id) if rule_id else None
    if rule is None:
        # Buscar la regla activa más reciente de devolución.
        from . import rules_engine

        rule = await rules_engine.return_rule(session)
    if rule is None:
        flow.status = "cancelled"
        await session.commit()
        return {
            "text": "No tengo una política de devolución cargada. "
            "¿Querés que lo revise un asesor?",
            "finished": True,
            "needs_handoff": True,
        }

    questions = _questions(rule)
    index = int(flow.step or 0)
    if index >= len(questions):
        flow.status = "completed"
        await session.commit()
        return {
            "text": "El flujo ya terminó. ¿Querés que lo revise un asesor?",
            "finished": True,
            "needs_handoff": True,
        }

    question = questions[index]
    answer_value = text.strip()
    if question.get("type", "text") == "yes_no":
        parsed = _yes_no(text)
        if parsed is None:
            return {
                "text": f"Para seguir necesito un sí o no. {question['text']}",
                "finished": False,
                "needs_handoff": False,
            }
        answer_value = parsed

    answers = dict(flow.answers or {})
    answers[question.get("key") or f"q{index + 1}"] = answer_value
    answers["_rule_id"] = rule.id
    flow.answers = answers
    flow.step = index + 1

    if flow.step < len(questions):
        await session.commit()
        next_question = questions[flow.step]
        return {
            "text": (
                f"Gracias. ({flow.step + 1}/{len(questions)}) "
                f"{next_question['text']}"
            ),
            "finished": False,
            "needs_handoff": False,
        }

    requirements = (rule.action or {}).get("requirements") or {}
    eligible = True
    for key, expected in requirements.items():
        if answers.get(key) != expected:
            eligible = False
            break

    flow.status = "completed"
    await session.commit()
    if eligible:
        return {
            "text": (
                "Con esos datos, la devolución cumple las condiciones. "
                "Ya avisé al equipo para coordinar el cambio."
            ),
            "finished": True,
            "needs_handoff": True,
        }
    return {
        "text": (
            "Con esos datos, el caso no cumple todas las condiciones de la "
            "política. Lo derivé a un asesor para revisarlo."
        ),
        "finished": True,
        "needs_handoff": True,
    }
