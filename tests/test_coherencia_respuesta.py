"""Guard de coherencia: la respuesta no habla de lo que nadie dijo."""

from __future__ import annotations

from app.services import coherence


def test_detecta_tema_inventado():
    respuesta = (
        "Antes de mostrarte cosas, ¿te vas de viaje o te quedás? "
        "Si te quedás te armo un plan de películas."
    )
    contexto = "Hola que tal! Algo para halloween"

    inventados = coherence.temas_inventados(respuesta, contexto)

    assert "viaje" in inventados
    assert "pelicula" in inventados or "películas" in inventados


def test_no_marca_lo_que_el_cliente_dijo():
    respuesta = "Para Halloween no tengo productos, pero puedo mostrarte velas."
    contexto = "Hola, busco algo para halloween"

    assert coherence.temas_inventados(respuesta, contexto) == []


def test_respuesta_neutra_es_coherente():
    respuesta = "Tenemos tres opciones de taladro con stock."
    contexto = "busco taladros"

    assert coherence.temas_inventados(respuesta, contexto) == []
