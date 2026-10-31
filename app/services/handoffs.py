"""Handoff queue: create, notify, take, reply and resolve."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (
    Advisor,
    Cart,
    Contact,
    Conversation,
    ConversationFlow,
    ConversationGuard,
    ConversationRecommendation,
    ConversationState,
    CustomerProfile,
    Handoff,
    HandoffEvent,
    HandoffNote,
    HandoffRead,
    HandoffSurvey,
    Message,
    Order,
)
from ..whatsapp import WhatsAppClient
from . import cart as cart_service

logger = logging.getLogger(__name__)

RESOLUTION_CATEGORIES = {
    "stock": "Stock",
    "precio": "Precio",
    "pago": "Pago",
    "entrega": "Entrega",
    "garantia": "Garantía",
    "otro": "Otro",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _waiting_minutes(handoff: Handoff, now: datetime) -> int:
    created = _aware(handoff.created_at)
    if created is None:
        return 0
    paused = int(handoff.sla_paused_seconds or 0)
    pause_start = _aware(handoff.sla_paused_at)
    if pause_start is not None:
        paused += max(0, int((now - pause_start).total_seconds()))
    return max(0, int((now - created).total_seconds() - paused) // 60)


async def _event(
    session: AsyncSession,
    handoff_id: str,
    action: str,
    advisor: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        HandoffEvent(
            handoff_id=handoff_id,
            advisor=(advisor or "")[:120] or None,
            action=action,
            detail=(detail or "")[:500] or None,
        )
    )


async def _choose_on_duty(session: AsyncSession) -> Advisor | None:
    advisors = list(
        (
            await session.scalars(
                select(Advisor).where(
                    Advisor.active.is_(True), Advisor.on_duty.is_(True)
                )
            )
        ).all()
    )
    if not advisors:
        return None
    scored = []
    for advisor in advisors:
        open_count = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(
                Handoff.assigned_to == advisor.display_name,
                Handoff.status.in_(("pending", "taken")),
            )
        )
        scored.append((int(open_count or 0), advisor.display_name, advisor))
    scored.sort(key=lambda row: (row[0], row[1]))
    return scored[0][2]


async def create_handoff(
    session: AsyncSession,
    conversation: Conversation,
    contact: Contact,
    reason: str = "",
    pausar: bool = False,
) -> tuple[Handoff, dict]:
    existing = await session.scalar(
        select(Handoff).where(
            Handoff.conversation_id == conversation.id,
            Handoff.status.in_(("pending", "taken")),
        )
    )
    if existing is not None:
        return existing, {"ok": True, "already_open": True}

    # El bot NO se pausa al crear el caso: sigue atendiendo consultas de
    # producto mientras un asesor lo revisa. Se pausa cuando lo toma.
    from . import presence

    dentro_horario = presence.office_open()
    assigned = await presence.pick_advisor(session) if dentro_horario else None
    # Sin asesor conectado con lugar (o fuera de horario) el caso queda en
    # cola: se asigna cuando alguien se conecta o libera un caso.
    estado = "pending" if assigned is not None else "queued"
    handoff = Handoff(
        conversation_id=conversation.id,
        reason=(reason or "El cliente pidió un asesor")[:300],
        status=estado,
        assigned_to=assigned.display_name if assigned else None,
    )
    session.add(handoff)
    # Solo se calla el bot cuando el cliente pidió una persona. En un
    # reclamo el bot sigue juntando datos para el asesor.
    if pausar:
        conversation.bot_paused = True
    await session.flush()
    await _event(
        session,
        handoff.id,
        "created",
        advisor=assigned.username if assigned else None,
        detail=(
            f"Asignado automáticamente a {assigned.display_name}"
            if assigned
            else reason
        ),
    )
    await session.commit()
    notification = await notify(session, handoff, contact, conversation)
    notification.update(
        {"queued": estado == "queued", "office_open": dentro_horario}
    )
    return handoff, notification


async def notify(
    session: AsyncSession,
    handoff: Handoff,
    contact: Contact,
    conversation: Conversation,
) -> dict:
    if not settings.handoff_notify_enabled:
        return {"ok": True, "skipped": "disabled"}
    payload = {
        "event": "handoff.created",
        "handoff_id": handoff.id,
        "reason": handoff.reason,
        "contact": {
            "wa_id": contact.wa_id,
            "name": contact.name,
            "phone": contact.phone_e164,
        },
        "conversation_id": conversation.id,
        "created_at": handoff.created_at.isoformat()
        if handoff.created_at
        else None,
    }
    delivered = False
    if settings.handoff_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    settings.handoff_webhook_url, json=payload
                )
                response.raise_for_status()
                delivered = True
        except Exception:  # noqa: BLE001 - no bloquear la atención al cliente
            logger.exception("No se pudo notificar el handoff %s", handoff.id)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            text = (
                "🔔 Nuevo handoff\n"
                f"Cliente: {contact.name or contact.wa_id}\n"
                f"Número: {contact.wa_id}\n"
                f"Motivo: {handoff.reason or 'Sin motivo'}\n"
                f"Bandeja: {settings.public_base_url}/admin/handoffs/view"
            )
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    (
                        "https://api.telegram.org/bot"
                        f"{settings.telegram_bot_token}/sendMessage"
                    ),
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
                delivered = True
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo enviar Telegram del handoff %s", handoff.id)
    if not delivered:
        return {
            "ok": True,
            "skipped": "no_notification_channel_configured",
        }
    handoff.notified_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "notified": True}


async def resume_sla_for_conversation(
    session: AsyncSession, conversation: Conversation
) -> None:
    handoff = await session.scalar(
        select(Handoff)
        .where(
            Handoff.conversation_id == conversation.id,
            Handoff.status.in_(("pending", "taken")),
        )
        .order_by(Handoff.created_at.desc())
    )
    if handoff is None or handoff.sla_paused_at is None:
        return
    paused_start = _aware(handoff.sla_paused_at)
    if paused_start is not None:
        handoff.sla_paused_seconds = int(handoff.sla_paused_seconds or 0) + max(
            0, int((datetime.now(timezone.utc) - paused_start).total_seconds())
        )
    handoff.sla_paused_at = None
    await session.commit()


async def reassign_stale_handoffs(
    session: AsyncSession, timeout_minutes: int = 5
) -> int:
    now = datetime.now(timezone.utc)
    stale = list(
        (
            await session.scalars(
                select(Handoff).where(
                    Handoff.status == "pending",
                    Handoff.assigned_to.is_not(None),
                )
            )
        ).all()
    )
    changed = 0
    for handoff in stale:
        created = _aware(handoff.created_at)
        if created is None or (now - created) < timedelta(
            minutes=max(timeout_minutes, 0)
        ):
            continue
        candidates = list(
            (
                await session.scalars(
                    select(Advisor).where(
                        Advisor.active.is_(True),
                        Advisor.on_duty.is_(True),
                        Advisor.display_name != handoff.assigned_to,
                    )
                )
            ).all()
        )
        scored = []
        for candidate in candidates:
            count = await session.scalar(
                select(func.count())
                .select_from(Handoff)
                .where(
                    Handoff.assigned_to == candidate.display_name,
                    Handoff.status.in_(("pending", "taken")),
                )
            )
            scored.append((int(count or 0), candidate.display_name, candidate))
        scored.sort(key=lambda row: (row[0], row[1]))
        previous = handoff.assigned_to
        handoff.assigned_to = scored[0][2].display_name if scored else None
        await _event(
            session,
            handoff.id,
            "reassigned" if scored else "unassigned",
            advisor=scored[0][2].username if scored else None,
            detail=(
                f"Reasignado de {previous} a {handoff.assigned_to}"
                if scored
                else f"Sin asesor disponible; se liberó de {previous}"
            ),
        )
        changed += 1
    if changed:
        await session.commit()
    return changed


async def advisor_metrics(session: AsyncSession, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    advisors = {
        row.username: row.display_name
        for row in (await session.scalars(select(Advisor))).all()
    }
    events = list(
        (
            await session.scalars(
                select(HandoffEvent)
                .where(HandoffEvent.created_at >= since)
                .order_by(HandoffEvent.created_at)
            )
        ).all()
    )
    handoffs = {
        row.id: row
        for row in (
            await session.scalars(
                select(Handoff).where(Handoff.created_at >= since)
            )
        ).all()
    }
    stats: dict[str, dict] = {}
    first_reply: dict[str, datetime] = {}
    for event in events:
        actor = event.advisor or "sistema"
        row = stats.setdefault(
            actor,
            {
                "advisor": advisors.get(actor, actor),
                "username": actor,
                "taken": 0,
                "resolved": 0,
                "reopened": 0,
                "replies": 0,
                "_response": [],
                "_resolution": [],
            },
        )
        handoff = handoffs.get(event.handoff_id)
        if event.action == "taken":
            row["taken"] += 1
        elif event.action == "replied":
            row["replies"] += 1
            first_reply.setdefault(event.handoff_id, _aware(event.created_at))
        elif event.action == "resolved":
            row["resolved"] += 1
            if handoff is not None and handoff.created_at:
                end = _aware(event.created_at)
                start = _aware(handoff.created_at)
                if end and start:
                    row["_resolution"].append(
                        max(0, (end - start).total_seconds() / 60)
                    )
        elif event.action == "reopened":
            row["reopened"] += 1
    for handoff_id, replied_at in first_reply.items():
        handoff = handoffs.get(handoff_id)
        if handoff is None or handoff.created_at is None or replied_at is None:
            continue
        created = _aware(handoff.created_at)
        if created is None:
            continue
        actor = (handoff.assigned_to or "").strip()
        # Buscar el username cuyo display_name coincide.
        username = next(
            (key for key, value in advisors.items() if value == actor),
            actor or "sistema",
        )
        row = stats.setdefault(
            username,
            {
                "advisor": advisors.get(username, username),
                "username": username,
                "taken": 0,
                "resolved": 0,
                "reopened": 0,
                "replies": 0,
                "_response": [],
                "_resolution": [],
            },
        )
        row["_response"].append(
            max(0, (replied_at - created).total_seconds() / 60)
        )
    result = []
    for row in stats.values():
        responses = row.pop("_response")
        resolutions = row.pop("_resolution")
        row["avg_response_minutes"] = (
            round(sum(responses) / len(responses), 1) if responses else None
        )
        row["avg_resolution_minutes"] = (
            round(sum(resolutions) / len(resolutions), 1)
            if resolutions
            else None
        )
        result.append(row)
    return sorted(result, key=lambda item: (-item["resolved"], item["advisor"]))


async def create_survey(
    session: AsyncSession, handoff: Handoff, contact: Contact
) -> HandoffSurvey:
    existing = await session.scalar(
        select(HandoffSurvey).where(HandoffSurvey.handoff_id == handoff.id)
    )
    if existing is not None:
        return existing
    survey = HandoffSurvey(
        token=secrets.token_urlsafe(24),
        handoff_id=handoff.id,
        contact_id=contact.id,
    )
    session.add(survey)
    await session.commit()
    return survey


async def get_survey(
    session: AsyncSession, token: str
) -> HandoffSurvey | None:
    return await session.scalar(
        select(HandoffSurvey).where(HandoffSurvey.token == token)
    )


async def answer_survey(
    session: AsyncSession, token: str, rating: int, comment: str | None
) -> dict:
    if rating < 1 or rating > 5:
        return {"ok": False, "reason": "rating_out_of_range"}
    survey = await get_survey(session, token)
    if survey is None:
        return {"ok": False, "reason": "survey_not_found"}
    survey.rating = rating
    survey.comment = (comment or "")[:2000] or None
    survey.answered_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True}


async def mark_read(
    session: AsyncSession, handoff_id: str, advisor: str
) -> None:
    existing = await session.scalar(
        select(HandoffRead).where(
            HandoffRead.handoff_id == handoff_id,
            HandoffRead.advisor == advisor,
        )
    )
    if existing is None:
        session.add(HandoffRead(handoff_id=handoff_id, advisor=advisor))
        await session.commit()


async def add_note(
    session: AsyncSession,
    handoff_id: str,
    advisor: str,
    text: str,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    note = HandoffNote(
        handoff_id=handoff_id,
        advisor=advisor,
        text=text[:3000],
    )
    session.add(note)
    await _event(session, handoff_id, "note", advisor=advisor, detail=text)
    await session.commit()
    return {"ok": True, "id": note.id}


async def list_handoffs(
    session: AsyncSession,
    status: str | None = None,
    advisor: str | None = None,
    advisor_name: str | None = None,
    view_all: bool = True,
) -> list[dict]:
    stmt = (
        select(Handoff, Conversation, Contact)
        .join(Conversation, Conversation.id == Handoff.conversation_id)
        .join(Contact, Contact.id == Conversation.contact_id)
        .order_by(Handoff.created_at.desc())
        .limit(100)
    )
    if status == "open":
        # Los casos en cola también se ven en la bandeja.
        stmt = stmt.where(
            Handoff.status.in_(("pending", "taken", "queued"))
        )
    elif status and status != "all":
        stmt = stmt.where(Handoff.status == status)
    if not view_all and advisor_name:
        stmt = stmt.where(
            (Handoff.assigned_to == advisor_name)
            | Handoff.assigned_to.is_(None)
        )
    rows = (await session.execute(stmt)).all()
    read_ids: set[str] = set()
    if advisor:
        read_ids = set(
            (
                await session.scalars(
                    select(HandoffRead.handoff_id).where(
                        HandoffRead.advisor == advisor
                    )
                )
            ).all()
        )
    now = datetime.now(timezone.utc)

    return [
        {
            "id": handoff.id,
            "status": handoff.status,
            "reason": handoff.reason,
            "assigned_to": handoff.assigned_to,
            "resolution_category": handoff.resolution_category,
            "created_at": handoff.created_at.isoformat()
            if handoff.created_at
            else None,
            "waiting_minutes": _waiting_minutes(handoff, now),
            "escalated": handoff.escalated_at is not None,
            "escalated_at": handoff.escalated_at.isoformat()
            if handoff.escalated_at
            else None,
            "sla_minutes": settings.handoff_sla_minutes,
            "sla_paused": handoff.sla_paused_at is not None,
            "overdue": _waiting_minutes(handoff, now)
            > settings.handoff_sla_minutes,
            "notified_at": handoff.notified_at.isoformat()
            if handoff.notified_at
            else None,
            "contact": contact.name or contact.wa_id,
            "wa_id": contact.wa_id,
            "unread": advisor is not None and handoff.id not in read_ids,
            "conversation_id": conversation.id,
        }
        for handoff, conversation, contact in rows
    ]


async def get_handoff(
    session: AsyncSession,
    handoff_id: str,
    advisor: str | None = None,
    advisor_name: str | None = None,
    is_admin: bool = False,
    is_supervisor: bool = False,
) -> dict | None:
    row = (
        await session.execute(
            select(Handoff, Conversation, Contact)
            .join(Conversation, Conversation.id == Handoff.conversation_id)
            .join(Contact, Contact.id == Conversation.contact_id)
            .where(Handoff.id == handoff_id)
        )
    ).first()
    if row is None:
        return None
    handoff, conversation, contact = row
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    ).all()
    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    orders = (
        await session.scalars(
            select(Order)
            .where(Order.contact_id == contact.id)
            .order_by(Order.created_at.desc())
            .limit(3)
        )
    ).all()
    cart = await session.scalar(
        select(Cart)
        .where(Cart.contact_id == contact.id, Cart.status == "active")
        .order_by(Cart.created_at.desc())
    )
    cart_data = await cart_service.summary(session, cart) if cart else None
    events = (
        await session.scalars(
            select(HandoffEvent)
            .where(HandoffEvent.handoff_id == handoff.id)
            .order_by(HandoffEvent.created_at.desc())
            .limit(20)
        )
    ).all()
    notes = (
        await session.scalars(
            select(HandoffNote)
            .where(HandoffNote.handoff_id == handoff.id)
            .order_by(HandoffNote.created_at.desc())
            .limit(30)
        )
    ).all()
    state = await session.scalar(
        select(ConversationState).where(
            ConversationState.conversation_id == conversation.id
        )
    )
    guard = await session.scalar(
        select(ConversationGuard).where(
            ConversationGuard.conversation_id == conversation.id
        )
    )
    recommendation = await session.scalar(
        select(ConversationRecommendation)
        .where(ConversationRecommendation.conversation_id == conversation.id)
        .order_by(ConversationRecommendation.created_at.desc())
        .limit(1)
    )
    flow = await session.scalar(
        select(ConversationFlow).where(
            ConversationFlow.conversation_id == conversation.id,
            ConversationFlow.status == "active",
        )
    )
    if advisor:
        await mark_read(session, handoff.id, advisor)
    is_mine = bool(advisor_name and handoff.assigned_to == advisor_name)
    can_act = is_mine or is_admin or is_supervisor
    can_take = handoff.status == "pending"
    can_reply = handoff.status == "taken" and can_act
    can_resolve = handoff.status == "taken" and can_act
    can_transfer = handoff.status == "taken" and can_act
    can_reopen = handoff.status in {"resolved", "returned"} and can_act
    now = datetime.now(timezone.utc)
    waiting = _waiting_minutes(handoff, now)
    return {
        "id": handoff.id,
        "status": handoff.status,
        "reason": handoff.reason,
        "assigned_to": handoff.assigned_to,
        "can_take": can_take,
        "can_reply": can_reply,
        "can_resolve": can_resolve,
        "can_transfer": can_transfer,
        "can_reopen": can_reopen,
        "notes": handoff.notes,
        "resolution_category": handoff.resolution_category,
        "created_at": handoff.created_at.isoformat()
        if handoff.created_at
        else None,
        "resolved_at": handoff.resolved_at.isoformat()
        if handoff.resolved_at
        else None,
        "waiting_minutes": waiting,
        "sla_minutes": settings.handoff_sla_minutes,
        "sla_paused": handoff.sla_paused_at is not None,
        "overdue": waiting > settings.handoff_sla_minutes,
        "contact": {
            "wa_id": contact.wa_id,
            "name": contact.name,
            "phone": contact.phone_e164,
        },
        "profile": {
            "city": profile.city if profile else None,
            "preferred_store": profile.preferred_store if profile else None,
            "preferences": profile.preferences if profile else {},
        },
        "orders": [
            {
                "number": order.number,
                "status": order.status,
                "total": str(order.total),
                "created_at": order.created_at.isoformat()
                if order.created_at
                else None,
            }
            for order in orders
        ],
        "cart": {
            "count": cart_data["count"],
            "total": str(cart_data["total"]),
            "items": [
                {
                    "name": line["name"],
                    "quantity": line["quantity"],
                }
                for line in cart_data["items"]
            ],
        }
        if cart_data
        else None,
        "events": [
            {
                "advisor": event.advisor,
                "action": event.action,
                "detail": event.detail,
                "created_at": event.created_at.isoformat()
                if event.created_at
                else None,
            }
            for event in events
        ],
        "notes": [
            {
                "id": note.id,
                "advisor": note.advisor,
                "text": note.text,
                "created_at": note.created_at.isoformat()
                if note.created_at
                else None,
            }
            for note in notes
        ],
        "unread": False,
        "conversation_id": conversation.id,
        "bot_paused": conversation.bot_paused,
        "context": {
            "state": {
                "intent": state.intent,
                "category": state.category,
                "brand": state.brand,
                "size": state.size,
                "min_price": str(state.min_price) if state.min_price is not None else None,
                "max_price": str(state.max_price) if state.max_price is not None else None,
                "last_sku": state.last_sku,
            }
            if state
            else None,
            "pending": {
                "slot": guard.pending_slot,
                "question": guard.pending_question,
                "query": guard.pending_query,
            }
            if guard
            else None,
            "last_recommendation": {
                "query": recommendation.query,
                "category": recommendation.category,
                "brand": recommendation.brand,
                "size": recommendation.size,
                "products": [
                    {
                        "sku": product.get("sku"),
                        "name": product.get("name"),
                        "brand": product.get("brand"),
                        "price": product.get("price"),
                    }
                    for product in (recommendation.products or [])[:4]
                    if isinstance(product, dict)
                ],
                "created_at": recommendation.created_at.isoformat()
                if recommendation.created_at
                else None,
            }
            if recommendation
            else None,
            "active_flow": {
                "flow": flow.flow,
                "step": flow.step,
                "status": flow.status,
            }
            if flow
            else None,
        },
        "messages": [
            {
                "id": message.id,
                "direction": message.direction,
                "type": message.type,
                "text": message.text,
                "payload": message.payload,
                "created_at": message.created_at.isoformat()
                if message.created_at
                else None,
            }
            for message in reversed(messages)
        ],
    }


async def resume_if_unattended(
    session: AsyncSession,
    conversation: Conversation,
    timeout_minutes: int = 15,
) -> bool:
    """Reactiva el bot si nadie tomó el handoff en el tiempo configurado."""
    handoff = await session.scalar(
        select(Handoff)
        .where(
            Handoff.conversation_id == conversation.id,
            Handoff.status == "pending",
        )
        .order_by(Handoff.created_at.desc())
    )
    if handoff is None or handoff.created_at is None:
        return False
    created = handoff.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created < timedelta(
        minutes=max(timeout_minutes, 0)
    ):
        return False
    conversation.bot_paused = False
    handoff.status = "resolved"
    handoff.notes = "Auto-resuelto: nadie tomó el caso a tiempo"
    handoff.resolved_at = datetime.now(timezone.utc)
    await _event(
        session,
        handoff.id,
        "auto_resumed",
        detail="El bot retomo la conversacion por falta de atencion.",
    )
    await session.commit()
    return True


async def sweep_stale_handoffs(
    session: AsyncSession,
    *,
    pending_minutes: int = 5,
    taken_minutes: int = 120,
) -> dict:
    """Cierra casos que nadie atendió, aunque el cliente no vuelva a escribir.

    ``resume_if_unattended`` solo corre cuando llega un mensaje; sin este
    barrido, un pendiente queda en la cola para siempre y ensucia el SLA.
    """
    now = datetime.now(timezone.utc)
    rows = (
        await session.scalars(
            select(Handoff).where(Handoff.status.in_(("pending", "taken")))
        )
    ).all()

    resolved = 0
    for handoff in rows:
        created = _aware(handoff.created_at)
        if created is None:
            continue
        limit = (
            pending_minutes
            if handoff.status == "pending"
            else taken_minutes
        )
        if now - created < timedelta(minutes=max(int(limit), 0)):
            continue

        conversation = await session.get(Conversation, handoff.conversation_id)
        if conversation is not None:
            conversation.bot_paused = False
        note = (
            "Auto-resuelto: nadie tomó el caso a tiempo"
            if handoff.status == "pending"
            else "Auto-resuelto: el asesor no respondió a tiempo"
        )
        handoff.status = "resolved"
        handoff.notes = note
        handoff.sla_paused_at = None
        handoff.resolved_at = now
        await _event(session, handoff.id, "auto_resumed", detail=note)
        resolved += 1

    if resolved:
        await session.commit()
    return {"ok": True, "resolved": resolved}


async def take_handoff(
    session: AsyncSession,
    handoff_id: str,
    assigned_to: str,
    advisor: str | None = None,
    is_admin: bool = False,
    whatsapp: Any | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    if handoff.status == "resolved":
        return {"ok": False, "reason": "already_resolved"}
    if (
        handoff.status == "taken"
        and handoff.assigned_to
        and handoff.assigned_to != assigned_to
        and not is_admin
    ):
        return {"ok": False, "reason": "already_taken"}
    handoff.status = "taken"
    handoff.assigned_to = assigned_to[:120]
    # Ahora sí el bot se calla: hay una persona atendiendo este chat.
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is not None:
        conversation.bot_paused = True
    await _event(
        session, handoff.id, "taken", advisor=advisor or assigned_to
    )
    await session.commit()

    # Saludo automático del asesor: el cliente debe saber que lo atendió una
    # persona con nombre, no quedar en silencio mientras el humano lee.
    if whatsapp is not None and conversation is not None:
        contact = await session.get(Contact, conversation.contact_id)
        if contact is not None:
            name = (contact.name or "").strip()
            greeting = (
                f"¡Hola{', ' + name if name else ''}! Soy "
                f"*{assigned_to}* del equipo de ROHO 👋 "
                "Ya estoy con tu consulta, contame un poco más y lo vemos juntos."
            )
            try:
                message_id = await whatsapp.send_text(contact.wa_id, greeting)
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        wa_message_id=message_id,
                        direction="out",
                        type="text",
                        text=greeting,
                    )
                )
                await session.commit()
            except Exception:  # noqa: BLE001 - no romper la toma del caso
                logger.exception("No se pudo enviar el saludo del asesor")

    return {"ok": True, "status": handoff.status}


async def resolve_handoff(
    session: AsyncSession,
    handoff_id: str,
    *,
    notes: str | None = None,
    category: str | None = None,
    return_to_bot: bool = True,
    advisor: str | None = None,
    whatsapp: Any | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    if not (notes or "").strip():
        return {"ok": False, "reason": "solution_required"}
    handoff.status = "resolved"
    handoff.notes = (notes or "")[:2000]
    handoff.resolution_category = category
    handoff.sla_paused_at = None
    handoff.resolved_at = datetime.now(timezone.utc)
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is not None and return_to_bot:
        conversation.bot_paused = False
    await _event(
        session,
        handoff.id,
        "resolved",
        advisor=advisor,
        detail=f"{category or 'otro'}: {notes}",
    )
    await session.commit()

    # Aviso de cierre: el cliente no debe quedar en silencio tras la gestión.
    if whatsapp is not None and conversation is not None and return_to_bot:
        contact = await session.get(Contact, conversation.contact_id)
        if contact is not None:
            try:
                await whatsapp.send_text(
                    contact.wa_id,
                    "Quedó resuelto ✅ Sigo yo por acá si necesitás algo más.",
                )
            except Exception:  # noqa: BLE001 - no romper el cierre por mensajería
                logger.exception("No se pudo avisar el cierre del handoff")

    return {"ok": True, "status": handoff.status}


async def return_to_bot(
    session: AsyncSession,
    handoff_id: str,
    reason: str,
    advisor: str | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    handoff.status = "returned"
    handoff.notes = reason[:2000]
    handoff.resolution_category = "devuelto_bot"
    handoff.sla_paused_at = None
    handoff.resolved_at = datetime.now(timezone.utc)
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is not None:
        conversation.bot_paused = False
    await _event(
        session, handoff.id, "returned_to_bot", advisor=advisor, detail=reason
    )
    await session.commit()
    return {"ok": True, "status": handoff.status}


async def reopen_handoff(
    session: AsyncSession,
    handoff_id: str,
    advisor: str | None = None,
    advisor_name: str | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    if handoff.status not in {"resolved", "returned"}:
        return {"ok": False, "reason": "not_closed"}
    handoff.status = "taken"
    handoff.assigned_to = advisor_name or handoff.assigned_to
    handoff.notes = None
    handoff.resolution_category = None
    handoff.resolved_at = None
    handoff.sla_paused_at = None
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is not None:
        conversation.bot_paused = True
    await _event(session, handoff.id, "reopened", advisor=advisor)
    await session.commit()
    return {"ok": True, "status": handoff.status}


async def transfer_handoff(
    session: AsyncSession,
    handoff_id: str,
    to_name: str,
    advisor: str | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    if handoff.status != "taken":
        return {"ok": False, "reason": "not_taken"}
    handoff.assigned_to = to_name[:120]
    await _event(
        session,
        handoff.id,
        "transferred",
        advisor=advisor,
        detail=f"Transferido a {to_name}",
    )
    await session.commit()
    return {"ok": True, "assigned_to": handoff.assigned_to}


async def reply_handoff(
    session: AsyncSession,
    handoff_id: str,
    text: str,
    wa: WhatsAppClient,
    advisor: str | None = None,
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        return {"ok": False, "reason": "handoff_not_found"}
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is None:
        return {"ok": False, "reason": "conversation_not_found"}
    contact = await session.get(Contact, conversation.contact_id)
    if contact is None:
        return {"ok": False, "reason": "contact_not_found"}
    try:
        message_id = await wa.send_text(contact.wa_id, text)
    except Exception as exc:  # noqa: BLE001 - mostrar error al asesor
        logger.exception("No se pudo enviar respuesta del handoff %s", handoff.id)
        return {
            "ok": False,
            "reason": "send_failed",
            "error": str(exc)[:300],
        }
    session.add(
        Message(
            conversation_id=conversation.id,
            wa_message_id=message_id,
            direction="out",
            type="text",
            text=text,
        )
    )
    if handoff.sla_paused_at is None:
        handoff.sla_paused_at = datetime.now(timezone.utc)
    await _event(session, handoff.id, "replied", advisor=advisor, detail=text)
    await session.commit()
    return {"ok": True, "message_id": message_id}
