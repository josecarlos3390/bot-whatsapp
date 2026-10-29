"""Una acción explícita del cliente siempre recibe su respuesta.

Los guards de calidad pueden variar o reemplazar una respuesta repetida. Eso
está bien para una charla, pero no cuando el cliente toca un botón: pidió ver
un producto, agregarlo o pagar, y tiene que verlo.
"""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import Contact
from app.services import actions
from app.whatsapp import Outbound


def test_reconoce_los_botones_de_producto_y_carrito():
    assert actions.es_accion("product:ABC123")
    assert actions.es_accion("add:ABC123:1")
    assert actions.es_accion("qty:ABC123:2")
    assert actions.es_accion("checkout")
    assert actions.es_accion("cart")


def test_reconoce_los_botones_de_navegacion():
    assert actions.es_accion("cat:cocina")
    assert actions.es_accion("type:Taladro percutor")
    assert actions.es_accion("uso:cargador celular")
    assert actions.es_accion("catalog")
    assert actions.es_accion("more")
    assert actions.es_accion("estado")


def test_un_mensaje_normal_no_es_accion():
    assert not actions.es_accion("hola")
    assert not actions.es_accion("busco un taladro")
    assert not actions.es_accion("")


def _respuesta():
    return Agent.__new__(Agent)


@pytest.mark.parametrize(
    "accion",
    ["product:ABC", "add:ABC:1", "cart", "checkout", "more", "cat:cocina"],
)
async def test_una_accion_no_se_reemplaza(session, monkeypatch, accion):
    """Aunque los guards dirían «repetido», la acción se responde igual."""
    from app.services import (
        coherence,
        conversation_guard,
        repeat_guard,
    )

    contacto = Contact(wa_id="59170100001", phone_e164="+59170100001")
    session.add(contacto)
    await session.commit()

    async def _siempre_repetida(*args, **kwargs):
        return True

    async def _nada_inventado(*args, **kwargs):
        return []

    monkeypatch.setattr(conversation_guard, "record_answer", _siempre_repetida)
    monkeypatch.setattr(repeat_guard, "repetida", _siempre_repetida)
    monkeypatch.setattr(
        repeat_guard, "respuesta_parecida", _siempre_repetida
    )
    monkeypatch.setattr(coherence, "contexto_reciente", _nada_inventado)
    monkeypatch.setattr(coherence, "temas_inventados", lambda *a, **k: [])

    agente = Agent()
    respuesta = _respuesta()
    entrada = [Outbound(text="Ficha del producto: Bs 279")]
    salida = await agente.postprocess(
        session, contacto, accion, __import__(
            "app.replies", fromlist=["AgentReply"]
        ).AgentReply(entrada)
    )

    texto = " ".join(m.text or "" for m in salida.messages)
    assert "Ficha del producto" in texto


async def test_un_mensaje_repetido_si_se_varia(session, monkeypatch):
    """La protección contra repetir sigue viva para la charla normal."""
    from app.services import conversation_guard

    contacto = Contact(wa_id="59170100002", phone_e164="+59170100002")
    session.add(contacto)
    await session.commit()

    async def _repetida(*args, **kwargs):
        return True

    monkeypatch.setattr(conversation_guard, "record_answer", _repetida)

    agente = Agent()
    from app.replies import AgentReply

    salida = await agente.postprocess(
        session,
        contacto,
        "hola",
        AgentReply([Outbound(text="Hola, ¿qué buscás hoy?")]),
    )

    texto = " ".join(m.text or "" for m in salida.messages)
    assert "Hola, ¿qué buscás hoy?" not in texto
