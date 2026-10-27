"""KPIs de asesores: tomados, resueltos, SLA, satisfacción y escalados."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import (
    Advisor,
    Contact,
    Conversation,
    Handoff,
    HandoffEvent,
    HandoffSurvey,
)
from app.services import advisors as advisor_service
from app.services import kpis


async def _caso(session, wa_id: str, *, estado: str = "resolved", dias: int = 1) -> Handoff:
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
        created_at=datetime.now(timezone.utc) - timedelta(days=dias),
    )
    session.add(caso)
    await session.commit()
    return caso


async def test_kpis_por_asesor(session):
    asesor = await advisor_service.create_advisor(session, "kpi1", "clave12345", "Kpi Uno")
    caso = await _caso(session, "59170011110")
    caso.assigned_to = asesor.display_name
    await session.commit()

    session.add(
        HandoffEvent(
            handoff_id=caso.id,
            advisor="kpi1",
            action="taken",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=50),
        )
    )
    session.add(
        HandoffEvent(
            handoff_id=caso.id,
            advisor="kpi1",
            action="replied",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=45),
        )
    )
    session.add(
        HandoffEvent(
            handoff_id=caso.id,
            advisor="kpi1",
            action="resolved",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
    )
    session.add(
        HandoffSurvey(
            handoff_id=caso.id,
            token="tok-kpi-1",
            contact_id=caso.conversation_id,
            rating=5,
        )
    )
    await session.commit()

    datos = await kpis.advisor_kpis(session, 30)
    fila = next(f for f in datos["advisors"] if f["username"] == "kpi1")

    assert fila["taken"] >= 1
    assert fila["resolved"] >= 1
    assert fila["avg_response_minutes"] is not None
    assert fila["sla_rate"] is not None
    assert datos["team"]["taken"] >= 1


async def test_kpis_cuentan_escalados(session):
    asesor = await advisor_service.create_advisor(session, "kpi2", "clave12345", "Kpi Dos")
    caso = await _caso(session, "59170011111", estado="pending")
    caso.assigned_to = asesor.display_name
    caso.escalated_at = datetime.now(timezone.utc)
    await session.commit()

    datos = await kpis.advisor_kpis(session, 7)

    assert datos["team"]["escalated_now"] >= 1
    assert any(f["escalated"] >= 1 for f in datos["advisors"])


async def test_periodo_vacio(session):
    datos = await kpis.advisor_kpis(session, 1)
    assert datos["days"] == 1
    assert "team" in datos and "advisors" in datos
