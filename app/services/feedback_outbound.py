"""Send due feedback surveys through an approved WhatsApp template."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, FeedbackRequest, Order
from ..whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)


async def send_due_surveys(
    session: AsyncSession,
    wa: WhatsAppClient,
    *,
    limit: int = 20,
) -> dict:
    if not settings.feedback_outbound_enabled:
        return {"sent": 0, "reason": "disabled"}
    if not settings.feedback_template_name:
        return {"sent": 0, "reason": "template_not_configured"}

    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(FeedbackRequest, Order, Contact)
            .join(Order, Order.id == FeedbackRequest.order_id)
            .join(Contact, Contact.id == FeedbackRequest.contact_id)
            .where(
                FeedbackRequest.status == "pending",
                FeedbackRequest.scheduled_for <= now,
                Contact.opt_in.is_(True),
            )
            .order_by(FeedbackRequest.scheduled_for)
            .limit(max(int(limit), 1))
        )
    ).all()
    sent = 0
    for request, order, contact in rows:
        try:
            await wa.send_template(
                contact.wa_id,
                settings.feedback_template_name,
                settings.feedback_template_lang,
                [contact.name or "cliente", order.number],
            )
        except Exception:  # noqa: BLE001 - reintentar en el próximo ciclo
            logger.exception(
                "No se pudo enviar encuesta del pedido %s", order.number
            )
            continue
        request.status = "asked"
        request.asked_at = now
        await session.commit()
        sent += 1
    return {"sent": sent, "due": len(rows)}
