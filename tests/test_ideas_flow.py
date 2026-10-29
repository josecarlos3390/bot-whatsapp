"""Ideas para una ocasión: el bot pregunta antes de mostrar productos."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app.services import emoji, ideas_flow


def test_el_boton_lleva_las_categorias():
    ideas = [
        {"idea": "armar la noche", "categorias": ["televisor", "sillón"]},
        {"idea": "comida a la parrilla", "categorias": ["parrilla"]},
    ]

    botones = ideas_flow.botones(ideas)

    assert len(botones) == 2
    assert botones[0]["title"] == "armar la noche"
    leido = ideas_flow.leer(botones[0]["id"])
    assert leido["i"] == "armar la noche"
    assert leido["c"] == ["televisor", "sillón"]


def test_no_pasa_de_tres_botones():
    ideas = [
        {"idea": f"idea {n}", "categorias": ["algo"]} for n in range(6)
    ]

    assert len(ideas_flow.botones(ideas)) == 3


def test_un_id_invalido_no_rompe():
    assert ideas_flow.leer("idea:no-es-json") is None
    assert ideas_flow.leer("otra-cosa") is None


def test_un_emoji_por_tema():
    assert emoji.para("televisor 43 pulgadas") == "📺"
    assert emoji.para("colchón de 2 plazas") == "🛏️"
    assert emoji.para("halloween") == "🎃"
    assert emoji.para("algo raro") == "🛍️"


async def test_pregunta_cuando_hay_varias_ideas(session):
    contacto = Contact(wa_id="59170050001", phone_e164="+59170050001")
    session.add(contacto)
    await session.commit()

    respuesta = await ideas_flow.preguntar(
        session,
        "halloween",
        [
            {"idea": "armar la noche", "categorias": ["televisor"]},
            {"idea": "comida a la parrilla", "categorias": ["parrilla"]},
        ],
    )

    assert respuesta is not None
    assert respuesta.messages[0].kind == "buttons"
    assert "¿Cuál te interesa?" in (respuesta.messages[0].text or "")


async def test_no_pregunta_si_hay_una_sola_idea(session):
    assert (
        await ideas_flow.preguntar(
            session,
            "halloween",
            [{"idea": "armar la noche", "categorias": ["televisor"]}],
        )
        is None
    )


async def test_responde_la_idea_elegida(session):
    session.add(
        CatalogItem(
            sku="IDEA-1",
            name="Juego de luces LED",
            price=299,
            stock=4,
            category="Iluminación",
            image_url="https://example.com/luces.png",
            active=True,
        )
    )
    contacto = Contact(wa_id="59170050002", phone_e164="+59170050002")
    session.add(contacto)
    await session.commit()

    import json

    raw = "idea:" + json.dumps(
        {"i": "decorar la casa", "c": ["luces led"]}, ensure_ascii=False
    )
    respuesta = await ideas_flow.responder_idea(
        session, contacto, raw, Agent()
    )

    assert respuesta is not None
    texto = " ".join(m.text or "" for m in respuesta.messages)
    assert "decorar la casa" in texto
    assert "luces LED" in texto
