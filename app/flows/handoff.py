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
    from ..agent import Toolbox, persona

    """Cliente enojado o esperando: disculpa y derivación inmediata."""
    toolbox = Toolbox(session, contact, agent.wa)
    try:
        await toolbox.tool_human_handoff(
            "Cliente enojado o esperando respuesta"
        )
    except Exception:  # noqa: BLE001 - la disculpa no se pierde
        logger.exception("No se pudo crear el handoff por frustración")
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=persona.frustration(),
                buttons=[{"id": "human", "title": "Hablar con alguien"}],
            )
        ]
    )



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

