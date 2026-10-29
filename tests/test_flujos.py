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


def test_los_flujos_de_menu_y_media_existen():
    from app.flows import media as media_flow
    from app.flows import menu as menu_flow

    assert callable(menu_flow.categories)
    assert callable(menu_flow.product_list)
    assert callable(menu_flow.idea)
    assert callable(media_flow.reply)

def test_el_flujo_de_derivacion_existe():
    from app.flows import handoff as handoff_flow

    assert callable(handoff_flow.fallback)
    assert callable(handoff_flow.frustration)
    assert callable(handoff_flow.empathy)


def test_empatia_responde_con_salida_amable():
    from app.flows import handoff as handoff_flow

    reply = handoff_flow.empathy(None, {"sensitive_topic": "duelo", "closing": False})

    assert reply.messages
    botones = [b["id"] for b in (reply.messages[0].buttons or [])]
    assert "human" in botones

def test_las_tarjetas_de_producto_se_arman():
    from app.flows import search as search_flow

    productos = [
        {
            "sku": "S-1",
            "name": "Sofá Bradford 2 Puestos",
            "price": "5990",
            "brand": "BRADFORD",
            "category": "Sofás",
            "description": "Un sofá cómodo",
            "image_url": "https://example.com/sofa.png",
        }
    ]

    mensajes = search_flow.cards(productos)

    assert any(m.kind == "text" for m in mensajes)
    assert any(m.kind == "list" for m in mensajes)
    # La foto se muestra recién al elegir el producto.
    assert not any(m.kind == "image" for m in mensajes)


def test_las_tarjetas_sin_imagen_van_como_texto():
    from app.flows import search as search_flow

    mensajes = search_flow.cards(
        [{"sku": "S-2", "name": "Silla", "price": "450"}]
    )

    assert any(m.kind == "text" for m in mensajes)

async def test_la_ficha_cierra_invitando_al_carrito(session):
    from app.agent import Agent
    from app.models import CatalogItem, Contact

    session.add(
        CatalogItem(
            sku="FICHA-1",
            name="Taladro de prueba 12V",
            price=500,
            stock=4,
            brand="INGCO",
            category="Taladros",
            active=True,
        )
    )
    contacto = Contact(wa_id="59170070001", phone_e164="+59170070001")
    session.add(contacto)
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "product:FICHA-1")
    cierre = respuesta.messages[-1]

    assert "carrito" in (cierre.text or "").lower()
    assert cierre.button_text == "Agregar"
    assert any(
        fila["id"].startswith("add:FICHA-1") for fila in cierre.sections[0]["rows"]
    )