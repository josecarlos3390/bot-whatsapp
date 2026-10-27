"""Presencia, tope de casos y cola de derivación."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from app.models import Advisor, Contact, Conversation, Handoff
from app.services import presence


async def _asesor(session, username: str, nombre: str, *, online: bool, max_cases: int = 5):
    from app.services import advisors

    fila = await advisors.create_advisor(session, username, "clave12345", nombre)
    fila.max_cases = max_cases
    fila.last_seen_at = datetime.now(timezone.utc) if online else None
    await session.commit()
    return fila


async def _caso(session, wa_id: str, estado: str = "queued") -> Handoff:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    caso = Handoff(conversation_id=conversacion.id, reason="prueba", status=estado)
    session.add(caso)
    await session.commit()
    return caso


def test_horario_de_oficina(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "office_hours_enabled", True)
    monkeypatch.setattr(settings, "office_hours_start", "09:00")
    monkeypatch.setattr(settings, "office_hours_end", "18:00")
    monkeypatch.setattr(settings, "office_hours_days", "1,2,3,4,5")

    lunes_10 = datetime(2026, 10, 26, 10, 0).astimezone()
    lunes_20 = datetime(2026, 10, 26, 20, 0).astimezone()
    sabado = datetime(2026, 10, 31, 11, 0).astimezone()

    assert presence.office_open(lunes_10) is True
    assert presence.office_open(lunes_20) is False
    assert presence.office_open(sabado) is False


async def test_asigna_al_conectado_con_lugar(session):
    asesor = await _asesor(session, "ana", "Ana", online=True, max_cases=5)

    caso = await _caso(session, "59170013331")
    asignados = await presence.assign_queued(session)

    await session.refresh(caso)
    assert asignados == 1
    assert caso.status == "pending"
    assert caso.assigned_to == asesor.display_name


async def test_no_asigna_a_quien_esta_desconectado(session):
    await _asesor(session, "beto", "Beto", online=False)

    caso = await _caso(session, "59170013332")
    asignados = await presence.assign_queued(session)

    await session.refresh(caso)
    assert asignados == 0
    assert caso.status == "queued"


async def test_respeta_el_tope_de_casos(session):
    from sqlalchemy import select

    lleno = await _asesor(session, "carla", "Carla", online=True, max_cases=1)
    # Solo Carla queda conectada.
    for otro in (await session.scalars(select(Advisor))).all():
        if otro.username != "carla":
            otro.last_seen_at = None
    # Carla ya tiene un caso abierto asignado a ella.
    abierto = await _caso(session, "59170013333", estado="pending")
    abierto.assigned_to = lleno.display_name
    await session.commit()

    caso = await _caso(session, "59170013334")
    asignados = await presence.assign_queued(session)

    await session.refresh(caso)
    assert asignados == 0
    assert caso.status == "queued"


async def test_se_reparte_al_liberarse_un_caso(session):
    unico = await _asesor(session, "dani", "Dani", online=True, max_cases=1)
    primero = await _caso(session, "59170013335")

    assert await presence.assign_queued(session) == 1
    segundo = await _caso(session, "59170013336")
    assert await presence.assign_queued(session) == 0

    # Dani resuelve el primero: ahora hay lugar para el segundo.
    primero.status = "resolved"
    await session.commit()
    assert await presence.assign_queued(session) == 1
    await session.refresh(segundo)
    assert segundo.assigned_to == unico.display_name


async def test_resumen_de_presencia(session):
    await _asesor(session, "eli", "Eli", online=True, max_cases=5)
    await _caso(session, "59170013337")

    resumen = await presence.presence_summary(session)

    assert resumen["queued"] == 1
    assert any(a["status"] == "online" for a in resumen["advisors"])
