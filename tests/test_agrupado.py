"""Mensajes seguidos: se contestan juntos."""

from __future__ import annotations

import asyncio

import pytest

from app.services import batching


@pytest.fixture(autouse=True)
def _limpiar():
    batching._buffer.clear()
    batching._pendientes.clear()
    yield
    for tarea in list(batching._pendientes.values()):
        tarea.cancel()
    batching._buffer.clear()
    batching._pendientes.clear()


def test_reconoce_los_botones_como_accion():
    assert batching.es_accion("product:ABC")
    assert batching.es_accion("cat:cocina")
    assert batching.es_accion("more")
    assert batching.es_accion("uso:cargador")


def test_un_texto_normal_no_es_accion():
    assert not batching.es_accion("hola")
    assert not batching.es_accion("busco un taladro")


def test_une_texto_y_conserva_la_foto():
    combinado = batching._unir(
        {"text": "Hola", "media": None, "wa_message_id": "1"},
        {
            "text": "[image]",
            "media": {"media_id": "m1", "kind": "image"},
            "wa_message_id": "2",
        },
    )

    assert combinado["text"] == "Hola"
    assert combinado["media"]["media_id"] == "m1"
    assert combinado["wa_message_id"] == "2"


def test_no_repite_el_mismo_texto():
    combinado = batching._unir(
        {"text": "Hola", "media": None, "wa_message_id": "1"},
        {"text": "Hola", "media": None, "wa_message_id": "2"},
    )

    assert combinado["text"] == "Hola"


async def test_procesa_el_grupo_una_sola_vez():
    procesados: list[dict] = []

    async def procesar(item: dict) -> None:
        procesados.append(item)

    await batching.agrupar(
        "59170090001", {"text": "Hola", "wa_message_id": "1"}, procesar, espera_ms=10
    )
    await batching.agrupar(
        "59170090001",
        {"text": "Mira esta foto", "wa_message_id": "2"},
        procesar,
        espera_ms=10,
    )
    await asyncio.sleep(0.1)

    assert len(procesados) == 1
    assert "Mira esta foto" in procesados[0]["text"]
    assert procesados[0]["wa_message_id"] == "2"


async def test_un_boton_responde_al_toque():
    procesados: list[dict] = []

    async def procesar(item: dict) -> None:
        procesados.append(item)

    await batching.agrupar(
        "59170090002",
        {"text": "product:ABC", "wa_message_id": "1"},
        procesar,
        espera_ms=5000,
    )

    assert len(procesados) == 1
    assert procesados[0]["text"] == "product:ABC"
