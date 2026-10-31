"""Reservar un producto con seña, desde la ficha.

El bot no cobra: deja la reserva anotada para que un asesor confirme el pago
de la seña. Lo que sí hace es dejar claro el beneficio y el plazo.
"""

from __future__ import annotations

from sqlalchemy import select

from ..models import Contact, Conversation
from ..replies import AgentReply
from ..whatsapp import Outbound
from ..services import catalog, handoffs

SENIA = 0.30
HORAS = 48


def _precio(valor: str | float | None) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _formato(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def reservar(agent, session, contact: Contact, sku: str) -> AgentReply:
    """Anota la reserva y la deja para un asesor."""
    producto = await catalog.get_item(session, sku)
    if producto is None:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text="No encontré ese producto. ¿Buscamos otra opción?",
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )
    precio = _precio(
        getattr(producto, "promo_price", None) or producto.price
    )
    senia = round(precio * SENIA, 2)
    nombre = (producto.name or "el producto")[:60]

    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    aviso = ""
    if conversacion is not None:
        try:
            await handoffs.create_handoff(
                session,
                conversacion,
                contact,
                reason=(
                    f"Quiere reservar {nombre} ({sku}) con seña de "
                    f"Bs {_formato(senia)}"
                ),
            )
            aviso = "\nYa avisé al equipo para que te confirme el pago 👌"
        except Exception:  # noqa: BLE001 - la reserva no debe romperse
            agent._trace("No se pudo crear el aviso de reserva")

    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=(
                    f"Listo, te reservo *{nombre}* 🤝\n\n"
                    f"• Seña: *Bs {_formato(senia)}* (30 %)\n"
                    f"• Te la guardamos {HORAS} horas\n"
                    f"• El saldo lo pagás al retirar o al recibir\n"
                    f"{aviso}\n"
                    "¿Querés que un asesor te pase los datos para la seña?"
                ),
                buttons=[
                    {"id": "human", "title": "Datos para la seña"},
                    {"id": "cart", "title": "Ver mi carrito"},
                ],
            )
        ]
    )
