from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent import AgentReply, Outbound
from ..config import settings
from ..models import Contact, Conversation, Message, utcnow
from ..runtime import agent, whatsapp
from . import outbox_health
from . import handoffs as handoff_service, metrics, output_guard
from . import memory as memory_service, native_commerce

logger = logging.getLogger(__name__)


def _phone(wa_id: str) -> str:
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    return f"+{digits}"


async def _history(
    session: AsyncSession, conversation_id: str, exclude_id: str | None = None
) -> list[dict]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(6)
    )
    if exclude_id:
        stmt = stmt.where(Message.id != exclude_id)
    rows = (await session.scalars(stmt)).all()
    history = []
    for row in reversed(rows):
        if not row.text:
            continue
        texto = row.text
        if row.direction == "in" and row.type == "audio":
            # Marcar el origen: si no, el modelo cree que no le llegó un audio.
            texto = f"🎤 (audio transcrito) {texto}"
        history.append(
            {
                "role": "user" if row.direction == "in" else "assistant",
                "content": texto,
            }
        )
    return history


async def _avisar_si_tarda(wa_id: str, deliver: bool) -> None:
    """Avisa que se está buscando cuando la respuesta demora."""
    await asyncio.sleep(settings.slow_reply_seconds)
    if not deliver:
        return
    try:
        await whatsapp.send_text(wa_id, "Dame un segundo, estoy buscando 🔎")
    except Exception:  # noqa: BLE001 - es un aviso, no debe romper
        logger.debug("No se pudo avisar la demora", exc_info=True)


async def ingest_inbound(
    session: AsyncSession,
    wa_id: str,
    text: str,
    wa_message_id: str,
    name: str | None = None,
    deliver: bool = True,
    order: dict | None = None,
    media: dict | None = None,
) -> list[dict]:
    """Guarda el mensaje, ejecuta el agente y envía la respuesta.

    Es idempotente por ``wa_message_id``: Meta puede reintentar el webhook.
    """
    native_order = (
        native_commerce.parse_order({"order": order}) if order else None
    )
    rubro_previo = None
    if native_order and native_order.items and not text:
        text = native_commerce.order_text(native_order)

    duplicate = await session.scalar(
        select(Message.id).where(Message.wa_message_id == wa_message_id)
    )
    if duplicate:
        logger.info("Mensaje duplicado ignorado: %s", wa_message_id)
        return []

    if deliver:
        # Doble check azul + "escribiendo…" mientras el bot arma la respuesta.
        asyncio.create_task(whatsapp.mark_read(wa_message_id))

    contact = await session.scalar(select(Contact).where(Contact.wa_id == wa_id))
    if contact is None:
        contact = Contact(wa_id=wa_id, phone_e164=_phone(wa_id), name=name)
        session.add(contact)
        await session.flush()
    elif name and not contact.name:
        contact.name = name

    # Nota de voz: se transcribe antes de guardar, así el agente recibe
    # texto y todo el resto del flujo funciona igual.
    if media and (media.get("kind") == "audio") and deliver:
        from . import transcription

        dicho = await transcription.desde_media(media)
        if dicho:
            text = dicho
            media = {**media, "transcripcion": dicho}
        else:
            text = "[audio]" if not text else text

    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversation is None:
        conversation = Conversation(contact_id=contact.id)
        session.add(conversation)
        await session.flush()

    # `last_message_at` se actualiza al final del turno: así el agente puede
    # medir la pausa y detectar una charla nueva en el mismo chat.
    await handoff_service.resume_sla_for_conversation(session, conversation)
    conversation_id = conversation.id
    inbound = Message(
        conversation_id=conversation_id,
        wa_message_id=wa_message_id,
        direction="in",
        type=(media or {}).get("kind") or ("order" if order else "text"),
        text=text,
        payload={
            "text": text,
            **({"order": order} if order else {}),
            **({"media": media} if media else {}),
        },
    )
    session.add(inbound)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.info("Mensaje duplicado (constraint): %s", wa_message_id)
        return []

    if (text or "").startswith("survey:"):
        try:
            _, token, rating_value = text.split(":", 2)
            result = await handoff_service.answer_survey(
                session, token, int(rating_value), None
            )
            if result.get("ok"):
                confirmation = "¡Gracias! Registramos tu calificación."
                message_id = (
                    await whatsapp.send_text(wa_id, confirmation)
                    if deliver
                    else f"dry-survey-{uuid.uuid4()}"
                )
                session.add(
                    Message(
                        conversation_id=conversation_id,
                        wa_message_id=message_id,
                        direction="out",
                        type="text",
                        text=confirmation,
                    )
                )
                await session.commit()
                return [{"ok": True, "survey": True}]
        except (ValueError, TypeError):
            logger.warning("Respuesta de encuesta inválida: %s", text)

    resumed_notice = False
    if conversation.bot_paused:
        wants_bot = (text or "").strip().lower() in {
            "menu",
            "menú",
            "bot",
            "volver al bot",
            "reiniciar",
        }
        resumed = await handoff_service.resume_if_unattended(
            session,
            conversation,
            timeout_minutes=0
            if wants_bot
            else settings.handoff_auto_resume_minutes,
        )
        if not resumed:
            logger.info(
                "Bot pausado para %s; mensaje guardado para humano", wa_id
            )
            # Si insiste, no se deja en silencio: se avisa una vez que el
            # equipo lo tiene y se guarda el mensaje para el asesor.
            from . import insistencia

            try:
                cuantos = await insistencia.esperando(session, contact)
            except Exception:  # noqa: BLE001 - nunca romper por esto
                cuantos = 0
            # Avisos en dos momentos exactos: al segundo mensaje sin
            # respuesta y al quinto. Así no se repite en cada mensaje.
            if cuantos == 2:
                return [
                    Outbound(text=insistencia.agradecer(contact.name))
                ]
            if cuantos == 5:
                return [
                    Outbound(text=insistencia.sin_respuesta(contact.name))
                ]
            return []
        resumed_notice = True

    if native_order and native_order.items:
        summary, errors = await native_commerce.replace_order_in_cart(
            session, contact, native_order
        )
        reply = AgentReply(
            [
                Outbound(
                    text=native_commerce.summary_text(summary, errors)
                )
            ]
        )
    else:
        history = await _history(
            session, conversation_id, exclude_id=inbound.id
        )
        memory = await memory_service.memory_text(
            session, contact, conversation_id
        )
        # Respuesta suelta ("para casa"): no debe quedar como rubro de la
        # charla. Se guarda y se restaura al terminar.
        rubro_previo = None
        if re.match(
            r"^(para|es para|uso|lo quiero para|seria para|sería para)\b",
            (text or "").strip().lower(),
        ) and len((text or "").split()) <= 4:
            conversacion = await session.get(Conversation, conversation_id)
            if conversacion is not None:
                rubro_previo = conversacion.last_query

        # Si la respuesta tarda, se avisa: evita los "???" del cliente.
        aviso_tarde = asyncio.create_task(
            _avisar_si_tarda(wa_id, deliver)
        )

        started = time.perf_counter()
        try:
            reply = await agent.handle(
                session, contact, text, history, memory=memory, media=media
            )
            metrics.record((time.perf_counter() - started) * 1000)
            aviso_tarde.cancel()
        except Exception:  # noqa: BLE001 - nunca dejar al cliente sin respuesta
            logger.exception(
                "Fallo el agente para el mensaje %s", wa_message_id
            )
            await session.rollback()
            reply = AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "No pude procesar eso en este momento. ¿Querés "
                            "que lo veamos de otra forma o te derivo con un "
                            "asesor?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver productos"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

    try:
        reply = await agent.postprocess(
            session, contact, text, reply
        )
    except Exception:  # noqa: BLE001 - nunca dejar el envío sin respuesta
        logger.exception("Fallo la guarda de conversación")
        await session.rollback()
        reply = AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "No quiero dejarte sin respuesta. ¿Buscás un producto "
                        "o preferís hablar con un asesor?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    # Última barrera: audita la respuesta antes de que salga al cliente.
    try:
        reply = await output_guard.sanitize(session, reply, text)
    except Exception:  # noqa: BLE001 - nunca bloquear el envío por el guard
        logger.exception("Falló la validación de salida")

    if resumed_notice:
        reply.messages.insert(
            0,
            Outbound(text="Sigo yo de nuevo 👋 ¿En qué te ayudo?"),
        )

    sent: list[dict] = []
    previous_kind: str | None = None
    for outbound in reply.messages:
        if deliver and previous_kind is not None:
            # Las imágenes tardan más en procesarse en el teléfono: tras una
            # foto se espera un poco más para respetar el orden de lectura.
            pausa = settings.outbound_pause_ms
            if previous_kind == "image":
                if outbound.kind in {"list", "buttons"}:
                    # El cierre espera a que WhatsApp procese la última foto:
                    # si no, aparece antes que la imagen en el teléfono.
                    pausa = settings.outbound_close_pause_ms
                else:
                    pausa = int(pausa * 1.5)
            if pausa > 0:
                await asyncio.sleep(pausa / 1000)
        previous_kind = outbound.kind
        if deliver:
            try:
                outbound_id = await whatsapp.send(wa_id, outbound)
                outbox_health.record_success()
            except Exception as exc:  # noqa: BLE001 - no perder el entrante
                outbox_health.record_failure(str(exc))
                logger.exception("No se pudo enviar la respuesta a %s", wa_id)
                continue
        else:
            outbound_id = f"sim-{uuid.uuid4()}"
        session.add(
            Message(
                conversation_id=conversation_id,
                wa_message_id=outbound_id,
                direction="out",
                type=outbound.kind,
                text=outbound.text,
                payload={
                    "kind": outbound.kind,
                    "buttons": outbound.buttons,
                    "url": outbound.url,
                },
            )
        )
        sent.append(
            {
                "kind": outbound.kind,
                "text": outbound.text,
                "url": outbound.url,
                "buttons": outbound.buttons,
                "sections": outbound.sections,
            }
        )
    # Una respuesta suelta no cambia el rubro de la charla.
    if rubro_previo is not None:
        conversacion = await session.get(Conversation, conversation_id)
        if conversacion is not None and conversacion.last_query != rubro_previo:
            conversacion.last_query = rubro_previo
    conversation.last_message_at = utcnow()
    await session.commit()
    await memory_service.maybe_schedule_summary(conversation_id)
    return sent
