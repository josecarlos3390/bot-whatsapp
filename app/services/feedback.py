"""Customer feedback capture and summaries."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, CustomerFeedback, FeedbackRequest, Order

logger = logging.getLogger(__name__)
ALLOWED_TYPES = {"service", "delivery", "product", "complaint", "open"}


async def create_feedback_request(
    session: AsyncSession,
    order: Order,
    *,
    type: str = "service",
) -> FeedbackRequest:
    existing = await session.scalar(
        select(FeedbackRequest).where(
            FeedbackRequest.order_id == order.id,
            FeedbackRequest.type == type,
        )
    )
    if existing is not None:
        return existing
    request = FeedbackRequest(
        contact_id=order.contact_id,
        order_id=order.id,
        type=type,
        status="pending",
        scheduled_for=datetime.now(timezone.utc)
        + timedelta(days=max(int(settings.feedback_delay_days), 0)),
    )
    session.add(request)
    await session.flush()
    return request


async def due_feedback_prompt(
    session: AsyncSession, contact_id: str
) -> str:
    now = datetime.now(timezone.utc)
    row = (
        await session.execute(
            select(FeedbackRequest, Order)
            .join(Order, Order.id == FeedbackRequest.order_id)
            .where(
                FeedbackRequest.contact_id == contact_id,
                FeedbackRequest.status == "pending",
                FeedbackRequest.scheduled_for <= now,
            )
            .order_by(FeedbackRequest.scheduled_for)
            .limit(1)
        )
    ).first()
    if row is None:
        return ""
    request, order = row
    request.status = "asked"
    request.asked_at = now
    await session.commit()
    if request.type == "delivery":
        question = (
            "preguntá una sola vez si la entrega llegó en el tiempo prometido"
        )
    else:
        question = (
            "preguntá una sola vez cómo calificás la atención de la compra "
            "(1-5)"
        )
    return (
        f"Encuesta pendiente del pedido {order.number}: {question}. "
        "Si no quiere responder, usá "
        f"skip_feedback(order_number='{order.number}')."
    )


async def skip_feedback(
    session: AsyncSession,
    contact_id: str,
    order_number: str | None = None,
) -> dict:
    stmt = select(FeedbackRequest).where(
        FeedbackRequest.contact_id == contact_id,
        FeedbackRequest.status.in_(("pending", "asked")),
    )
    if order_number:
        order = await session.scalar(
            select(Order).where(
                Order.number == order_number.strip(),
                Order.contact_id == contact_id,
            )
        )
        if order is None:
            return {"ok": False, "reason": "order_not_found"}
        stmt = stmt.where(FeedbackRequest.order_id == order.id)
    request = await session.scalar(stmt.order_by(FeedbackRequest.created_at))
    if request is None:
        return {"ok": True, "message": "No había encuesta pendiente."}
    request.status = "skipped"
    request.answered_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "message": "Encuesta omitida."}


async def mark_delivered(session: AsyncSession, order_number: str) -> dict:
    order = await session.scalar(
        select(Order).where(Order.number == order_number.strip())
    )
    if order is None:
        return {"ok": False, "reason": "order_not_found"}
    if order.status not in {"paid", "invoiced"}:
        return {"ok": False, "reason": "order_not_paid"}
    order.delivered_at = datetime.now(timezone.utc)
    request = await session.scalar(
        select(FeedbackRequest).where(
            FeedbackRequest.order_id == order.id,
            FeedbackRequest.type == "delivery",
        )
    )
    if request is None:
        request = FeedbackRequest(
            contact_id=order.contact_id,
            order_id=order.id,
            type="delivery",
            status="pending",
            scheduled_for=datetime.now(timezone.utc),
        )
        session.add(request)
    else:
        request.scheduled_for = datetime.now(timezone.utc)
        if request.status == "skipped":
            request.status = "pending"
    await session.commit()
    return {"ok": True, "order_number": order.number, "request_id": request.id}


async def pending_requests(session: AsyncSession) -> list[dict]:
    rows = (
        await session.execute(
            select(FeedbackRequest, Order, Contact)
            .join(Order, Order.id == FeedbackRequest.order_id)
            .join(Contact, Contact.id == FeedbackRequest.contact_id)
            .where(FeedbackRequest.status.in_(("pending", "asked")))
            .order_by(FeedbackRequest.scheduled_for)
        )
    ).all()
    return [
        {
            "request_id": request.id,
            "status": request.status,
            "type": request.type,
            "scheduled_for": request.scheduled_for.isoformat()
            if request.scheduled_for
            else None,
            "asked_at": request.asked_at.isoformat() if request.asked_at else None,
            "order_number": order.number,
            "contact": contact.name or contact.wa_id,
            "wa_id": contact.wa_id,
        }
        for request, order, contact in rows
    ]


async def complaints(
    session: AsyncSession, include_acknowledged: bool = False
) -> list[dict]:
    stmt = (
        select(CustomerFeedback, Contact, Order)
        .join(Contact, Contact.id == CustomerFeedback.contact_id)
        .outerjoin(Order, Order.id == CustomerFeedback.order_id)
        .where(
            (CustomerFeedback.type == "complaint")
            | (CustomerFeedback.rating <= 2)
        )
        .order_by(CustomerFeedback.created_at.desc())
        .limit(100)
    )
    if not include_acknowledged:
        stmt = stmt.where(CustomerFeedback.acknowledged_at.is_(None))
    rows = (await session.execute(stmt)).all()
    return [
        {
            "feedback_id": feedback_row.id,
            "type": feedback_row.type,
            "rating": feedback_row.rating,
            "comment": feedback_row.comment,
            "sku": feedback_row.sku,
            "order_number": order.number if order else None,
            "contact": contact.name or contact.wa_id,
            "wa_id": contact.wa_id,
            "created_at": feedback_row.created_at.isoformat()
            if feedback_row.created_at
            else None,
            "acknowledged_at": feedback_row.acknowledged_at.isoformat()
            if feedback_row.acknowledged_at
            else None,
        }
        for feedback_row, contact, order in rows
    ]


async def acknowledge(session: AsyncSession, feedback_id: str) -> dict:
    row = await session.get(CustomerFeedback, feedback_id)
    if row is None:
        return {"ok": False, "reason": "feedback_not_found"}
    row.acknowledged_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "feedback_id": feedback_id}


async def record_feedback(
    session: AsyncSession,
    contact_id: str,
    *,
    type: str,
    rating: int | None = None,
    comment: str | None = None,
    order_number: str | None = None,
    sku: str | None = None,
    consent: bool = True,
) -> dict:
    feedback_type = (type or "open").strip().lower()
    if feedback_type not in ALLOWED_TYPES:
        raise ValueError(f"Tipo de feedback inválido: {type}")
    if rating is not None and not 1 <= int(rating) <= 5:
        raise ValueError("El rating debe estar entre 1 y 5.")
    if not consent:
        return {"ok": False, "reason": "consent_required"}

    order = None
    if order_number:
        order = await session.scalar(
            select(Order).where(
                Order.number == order_number.strip(),
                Order.contact_id == contact_id,
            )
        )
        if order is None:
            return {"ok": False, "reason": "order_not_found"}

    text = (comment or "").strip()[:1000] or None
    row = CustomerFeedback(
        contact_id=contact_id,
        order_id=order.id if order else None,
        type=feedback_type,
        rating=int(rating) if rating is not None else None,
        comment=text,
        sku=(sku or "").strip().upper() or None,
        consent=True,
    )
    session.add(row)
    await session.commit()

    request_stmt = select(FeedbackRequest).where(
        FeedbackRequest.contact_id == contact_id,
        FeedbackRequest.status.in_(("pending", "asked")),
    )
    if feedback_type in {"service", "delivery"}:
        request_stmt = request_stmt.where(
            FeedbackRequest.type == feedback_type
        )
    if order is not None:
        request_stmt = request_stmt.where(FeedbackRequest.order_id == order.id)
    feedback_request = await session.scalar(
        request_stmt.order_by(FeedbackRequest.created_at)
    )
    if feedback_request is not None:
        feedback_request.status = "answered"
        feedback_request.answered_at = datetime.now(timezone.utc)
        await session.commit()

    needs_attention = feedback_type == "complaint" or (
        row.rating is not None and row.rating <= 2
    )
    return {
        "ok": True,
        "feedback_id": row.id,
        "type": feedback_type,
        "needs_attention": needs_attention,
        "message": "Gracias, guardé tu respuesta.",
    }


async def feedback_summary(
    session: AsyncSession,
    *,
    contact_id: str | None = None,
    sku: str | None = None,
) -> dict:
    stmt = select(
        func.count(CustomerFeedback.id),
        func.avg(CustomerFeedback.rating),
    )
    if contact_id:
        stmt = stmt.where(CustomerFeedback.contact_id == contact_id)
    if sku:
        stmt = stmt.where(CustomerFeedback.sku == sku.strip().upper())
    count, average = (await session.execute(stmt)).one()

    type_stmt = select(
        CustomerFeedback.type,
        func.count(CustomerFeedback.id),
        func.avg(CustomerFeedback.rating),
    )
    if contact_id:
        type_stmt = type_stmt.where(CustomerFeedback.contact_id == contact_id)
    if sku:
        type_stmt = type_stmt.where(CustomerFeedback.sku == sku.strip().upper())
    type_stmt = type_stmt.group_by(CustomerFeedback.type)

    recent_stmt = select(CustomerFeedback)
    if contact_id:
        recent_stmt = recent_stmt.where(
            CustomerFeedback.contact_id == contact_id
        )
    if sku:
        recent_stmt = recent_stmt.where(
            CustomerFeedback.sku == sku.strip().upper()
        )
    recent_stmt = recent_stmt.order_by(CustomerFeedback.created_at.desc()).limit(5)
    recent = (await session.scalars(recent_stmt)).all()
    pending = await session.scalar(
        select(func.count())
        .select_from(FeedbackRequest)
        .where(
            FeedbackRequest.status.in_(("pending", "asked")),
            *(
                [FeedbackRequest.contact_id == contact_id]
                if contact_id
                else []
            ),
        )
    )

    return {
        "count": int(count or 0),
        "average_rating": round(float(average), 2) if average is not None else None,
        "pending_requests": int(pending or 0),
        "by_type": [
            {
                "type": feedback_type,
                "count": int(total),
                "average_rating": round(float(avg), 2) if avg is not None else None,
            }
            for feedback_type, total, avg in (
                await session.execute(type_stmt)
            ).all()
        ],
        "recent": [
            {
                "type": row.type,
                "rating": row.rating,
                "comment": row.comment,
                "sku": row.sku,
                "created_at": row.created_at.isoformat()
                if row.created_at
                else None,
            }
            for row in recent
        ],
    }
