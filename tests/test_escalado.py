"""Escalado: los casos que esperan demasiado quedan marcados."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Contact, Conversation, Handoff, HandoffEvent
from app.services import escalation


async def _caso(session, wa_id: str, *, minutos: int, estado: str = "queued") -> Handoff:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    caso = Handoff(
        conversation_id=conversacion.id,
        reason="prueba",
        status=estado,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutos),
    )
    session.add(caso)
    await session.commit()
    return caso


async def test_escala_un_caso_que_espera(session):
    caso = await _caso(session, "59170012221", minutos=30)

    resultado = await escalation.escalate_stale(session)

    await session.refresh(caso)
    assert resultado["escalated"] >= 1
    assert caso.escalated_at is not None


async def test_no_escala_un_caso_reciente(session):
    caso = await _caso(session, "59170012222", minutos=1)

    await escalation.escalate_stale(session)

    await session.refresh(caso)
    assert caso.escalated_at is None


async def test_no_repite_el_escalado(session):
    await _caso(session, "59170012223", minutos=30)
    primera = await escalation.escalate_stale(session)
    segunda = await escalation.escalate_stale(session)

    assert primera["escalated"] >= 1
    assert segunda["escalated"] == 0


async def test_resumen_de_espera(session):
    await _caso(session, "59170012224", minutos=2, estado="queued")
    resumen = await escalation.summary(session)

    assert resumen["queued"] >= 1
    assert resumen["oldest_minutes"] >= 2
