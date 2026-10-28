"""Flujos extraídos: la ficha y los atributos viven fuera de agent.py."""

from __future__ import annotations

from app.agent import Agent
from app.flows import product as product_flow
from app.replies import AgentReply


def test_la_respuesta_es_importable_desde_su_modulo():
    from app.whatsapp import Outbound

    reply = AgentReply([Outbound(text="hola")])

    assert reply.messages[0].text == "hola"


def test_el_agente_reexporta_la_respuesta():
    from app.agent import AgentReply as DesdeAgente

    assert DesdeAgente is AgentReply


def test_los_flujos_exponen_detalle_y_atributo():
    assert callable(product_flow.detail)
    assert callable(product_flow.attribute)


def test_la_descripcion_corta_se_comparte():
    from app.flows.text import card_description

    assert Agent._card_description("  Hola   mundo  ") == "Hola mundo"
    assert card_description("<p>Hola <b>mundo</b></p>") == "Hola mundo"
