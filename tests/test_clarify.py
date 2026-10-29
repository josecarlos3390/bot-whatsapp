"""Preguntar el uso cuando el pedido es demasiado abierto."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import clarify


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_detecta_pedidos_amplios():
    assert clarify.es_amplio("que productos de tecnologia tenes?")
    assert clarify.es_amplio("necesito algo para mi casa")
    assert clarify.es_amplio("que opciones hay")


def test_no_pregunta_si_el_pedido_es_concreto():
    assert not clarify.es_amplio("busco un colchón de 2 plazas")
    assert not clarify.es_amplio("taladro percutor 13mm ingco")
    assert not clarify.es_amplio("")


def test_parsea_la_pregunta_de_la_ia():
    datos = clarify.parsear(
        '{"preguntar": true, "pregunta": "¿Para qué lo necesitás?",'
        ' "opciones": [{"titulo": "Celular", "consulta": "cargador celular"},'
        ' {"titulo": "Auto", "consulta": "cargador auto"}]}'
    )

    assert datos is not None
    assert datos["pregunta"] == "¿Para qué lo necesitás?"
    assert [o["consulta"] for o in datos["opciones"]] == [
        "cargador celular",
        "cargador auto",
    ]


def test_no_pregunta_si_la_ia_dice_que_alcanza():
    assert clarify.parsear('{"preguntar": false}') is None


def test_rechaza_preguntas_sin_opciones_suficientes():
    assert (
        clarify.parsear(
            '{"preguntar": true, "pregunta": "¿Uso?",'
            ' "opciones": [{"titulo": "A", "consulta": "algo"}]}'
        )
        is None
    )


def test_rechaza_respuestas_invalidas():
    assert clarify.parsear("no sé") is None
    assert clarify.parsear("{}") is None


async def test_sin_clave_no_pregunta(session, monkeypatch):
    from app.models import Contact
    from app.agent import Agent

    contacto = Contact(wa_id="59170080001", phone_e164="+59170080001")
    session.add(contacto)
    await session.commit()

    assert (
        await clarify.preguntar(
            Agent(), session, contacto, "necesito algo para mi casa"
        )
        is None
    )
