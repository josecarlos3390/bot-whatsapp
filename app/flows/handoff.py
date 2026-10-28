"""Derivación a asesores: fallback, frustración y empatía.

Extraído de `agent.py` para que el enrutamiento no crezca.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact
from ..replies import AgentReply
from ..whatsapp import Outbound

logger = logging.getLogger(__name__)


async def fallback(
    agent, session: AsyncSession, contact: Contact, reason: str
) -> AgentReply:
    """Deriva con honestidad cuando el bot no puede responder."""
    from ..agent import Toolbox, persona

    toolbox = Toolbox(session, contact, agent.wa)
    notification: dict = {}
    try:
        resultado = await toolbox.tool_human_handoff(reason[:200])
        notification = resultado.get("notification") or {}
    except Exception:  # noqa: BLE001 - no dejar sin respuesta
        logger.exception("No se pudo crear el handoff de aclaración")
    if notification.get("queued"):
        agent._trace("Derivación en cola")
        texto = persona.handoff_queued(
            office_open=bool(notification.get("office_open", True))
        )
    else:
        texto = (
            "Para no darte una respuesta incorrecta, te derivo con un "
            "asesor. ¿Querés que siga con otra consulta mientras tanto?"
        )
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=texto,
                buttons=[
                    {"id": "catalog", "title": "Ver productos"},
                    {"id": "human", "title": "Asesor"},
                ],
            )
        ]
    )



async def frustration(
    agent, session: AsyncSession, contact: Contact
) -> AgentReply:
    """Cliente enojado o esperando: disculpa y derivación inmediata."""
    from sqlalchemy import select

    from ..agent import Toolbox, persona
    from ..models import Message

    toolbox = Toolbox(session, contact, agent.wa)
    try:
        await toolbox.tool_human_handoff(
            "Cliente enojado o esperando respuesta"
        )
    except Exception:  # noqa: BLE001 - la disculpa no se pierde
        logger.exception("No se pudo crear el handoff por frustración")

    # Si ya nos disculpamos hace un momento, no se repite el mismo texto:
    # el cliente enojado nota la repetición y se enoja más.
    if await _ya_se_disculpo(agent, session, contact):
        agent._trace("Enojo: ya derivado, se evita repetir")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Tu caso ya está con una persona del equipo. "
                        "Para no repetirte el mismo mensaje: si me dejás el "
                        "número de pedido lo adjunto, y si preferís que te "
                        "llamen, decime el horario en que te queda bien."
                    ),
                    buttons=[
                        {"id": "estado", "title": "Ver mi pedido"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=persona.frustration(),
                buttons=[{"id": "human", "title": "Hablar con alguien"}],
            )
        ]
    )


async def _ya_se_disculpo(agent, session, contact: Contact) -> bool:
    """¿La última respuesta del bot ya fue la disculpa por enojo?"""
    from sqlalchemy import select

    from ..agent import persona
    from ..models import Conversation, Message

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
    inicio = persona.frustration()[:40].lower()
    return inicio and ultimo.strip().lower().startswith(inicio)



def empathy(agent, decision: dict) -> AgentReply:
    """Ante algo delicado: empatía, cero venta y una salida amable."""
    from ..agent import persona

    """Ante algo delicado: empatía, cero venta y una salida amable."""
    text = persona.empathy(
        decision.get("sensitive_topic"), closing=bool(decision.get("closing"))
    )
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=text,
                buttons=[
                    {"id": "human", "title": "Hablar con alguien"},
                    {"id": "catalog", "title": "Seguir con productos"},
                ],
            )
        ]
    )

