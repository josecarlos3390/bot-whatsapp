"""Revisión del aprendizaje: aprobar, corregir o descartar."""

from __future__ import annotations

from app.models import QueryLearning
from app.services import learning


async def test_lo_aprendido_queda_pendiente(session):
    await learning.remember(session, term="perforadora", query="taladro percutor")

    from sqlalchemy import select

    fila = await session.scalar(
        select(QueryLearning).where(QueryLearning.term == "perforadora")
    )
    assert fila is not None
    assert fila.status == "pending"


async def test_aprobar_conserva_el_uso(session):
    await learning.remember(session, term="amoladora", query="amoladora angular")
    pendientes = await learning.pending(session)
    objetivo = next(p for p in pendientes if p["term"] == "amoladora")

    resultado = await learning.decide(session, objetivo["id"], approve=True)

    assert resultado["status"] == "approved"
    assert await learning.recall(session, "amoladora") == "amoladora angular"


async def test_descartar_deja_de_usarse(session):
    await learning.remember(session, term="coso", query="taladro")
    pendientes = await learning.pending(session)
    objetivo = next(p for p in pendientes if p["term"] == "coso")

    await learning.decide(session, objetivo["id"], approve=False)

    assert await learning.recall(session, "coso") is None


async def test_corregir_guarda_la_consulta_nueva(session):
    await learning.remember(session, term="perfo", query="taladro")
    pendientes = await learning.pending(session)
    objetivo = next(p for p in pendientes if p["term"] == "perfo")

    resultado = await learning.decide(
        session, objetivo["id"], approve=True, query="taladro percutor 13mm"
    )

    assert resultado["query"] == "taladro percutor 13mm"
    assert await learning.recall(session, "perfo") == "taladro percutor 13mm"
