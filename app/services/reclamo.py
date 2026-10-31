"""Reclamos: el bot toma los datos y los deja listos para el asesor.

Sin esto, después de «¿qué producto es y qué pasó?» el bot volvía a buscar
productos y se perdía el caso.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select

from ..models import Contact, Conversation
from ..replies import AgentReply
from ..whatsapp import Outbound
from . import handoffs

MARCA = "RECLAMO:"
CIERRE = "FIN"
logger = logging.getLogger(__name__)

# Cuántos datos se piden antes de cerrar la toma.
PEDIDOS = 2


def _resumen(conversacion: Conversation) -> str:
    return (conversacion.summary or "").strip()


def activo(conversacion: Conversation | None) -> bool:
    if conversacion is None:
        return False
    resumen = _resumen(conversacion)
    return resumen.startswith(MARCA) and not resumen.endswith(CIERRE)


def detalles(conversacion: Conversation) -> list[str]:
    resumen = _resumen(conversacion)
    if not resumen:
        return []
    cuerpo = resumen[len(MARCA) :].replace(CIERRE, "").strip()
    return [parte.strip() for parte in cuerpo.split("|") if parte.strip()]


async def _conversacion(session, contact: Contact) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )


async def iniciar(
    session, contact: Contact, texto: str, agent=None
) -> AgentReply:
    """El cliente contó un problema: se abre el caso y se piden los datos."""
    conversacion = await _conversacion(session, contact)
    if conversacion is None:
        return AgentReply(
            [Outbound(text="Contame qué pasó con tu pedido, por favor.")]
        )
    conversacion.summary = f"{MARCA} {texto.strip()[:400]}"
    await session.commit()
    if agent is not None:
        agent._trace("Reclamo iniciado")
    return AgentReply(
        [
            Outbound(
                text=(
                    "Lamento lo ocurrido. Ya avisé a alguien del equipo para "
                    "revisar el caso. ¿Me contás qué producto es y qué pasó?"
                )
            )
        ]
    )


async def continuar(
    session, contact: Contact, texto: str, agent=None
) -> AgentReply:
    """Suma el dato al caso y cierra cuando ya está completo."""
    conversacion = await _conversacion(session, contact)
    if conversacion is None:
        return AgentReply([Outbound(text="Contame qué pasó, por favor.")])
    limpio = (texto or "").strip()[:300]
    if limpio:
        conversacion.summary = f"{_resumen(conversacion)} | {limpio}"
    partes = detalles(conversacion)
    if agent is not None:
        agent._trace(f"Reclamo: {len(partes)} dato(s)")
    if len(partes) >= PEDIDOS + 1:
        conversacion.summary = f"{_resumen(conversacion)} {CIERRE}".strip()
        await _avisar(session, contact, conversacion)
        await session.commit()
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Listo, ya quedó registrado el caso con lo que me "
                        "contaste. Un asesor del equipo te escribe hoy.\n\n"
                        "¿Querés que te muestre algo mientras esperás?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Hablar con asesor"},
                    ],
                )
            ]
        )
    await session.commit()
    faltan = PEDIDOS + 1 - len(partes)
    if faltan >= 2:
        pregunta = "¿Me contás qué producto es y qué pasó?"
    else:
        pregunta = "¿Me falta un dato: tenés el número de pedido o la factura?"
    return AgentReply(
        [Outbound(text=f"Gracias. {pregunta}")]
    )


async def _avisar(session, contact: Contact, conversacion: Conversation) -> None:
    """Deja el reclamo en la bandeja con el detalle completo."""
    try:
        await handoffs.create_handoff(
            session,
            conversacion,
            contact,
            reason=f"Reclamo: {_resumen(conversacion)[:250]}",
        )
    except Exception:  # noqa: BLE001 - el caso no debe perderse por esto
        logger.debug("No se pudo crear el aviso del reclamo", exc_info=True)


def es_cierre(texto: str) -> bool:
    return bool(re.search(r"\b(nada m[aá]s|eso es todo|gracias)\b", texto or ""))
