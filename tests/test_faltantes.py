"""Informe de faltantes: lo que piden y no está en el catálogo."""

from __future__ import annotations

from app.models import MissingRequest
from app.services import missing


async def test_registra_el_termino(session):
    await missing.record(
        session,
        "paraguas",
        intent="cubrirse de la lluvia",
        related=["Sombrilla parasol"],
        answered=True,
    )

    datos = await missing.resumen(session, dias=30)
    assert datos["total"] == 1
    assert datos["con_respuesta"] == 1
    assert datos["terminos"][0]["term"] == "paraguas"
    assert datos["terminos"][0]["intencion"] == "cubrirse de la lluvia"


async def test_cuenta_las_repeticiones(session):
    await missing.record(session, "bicicletas")
    await missing.record(session, "bicicletas")
    await missing.record(session, "piscinas")

    datos = await missing.resumen(session, dias=30)

    assert datos["total"] == 3
    primero = datos["terminos"][0]
    assert primero["term"] == "bicicletas"
    assert primero["veces"] == 2


async def test_ignora_terminos_vacios(session):
    await missing.record(session, "   ")

    datos = await missing.resumen(session, dias=30)
    assert datos["total"] == 0


async def test_guarda_los_relacionados(session):
    await missing.record(
        session, "paraguas", intent="sol", related=["Sombrilla", "Base"]
    )

    from sqlalchemy import select

    fila = await session.scalar(
        select(MissingRequest).where(MissingRequest.term == "paraguas")
    )
    assert fila is not None
    assert "Sombrilla" in (fila.related or "")
