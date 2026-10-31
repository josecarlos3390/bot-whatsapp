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

async def test_la_foto_con_opciones_no_pregunta_de_mas(session, monkeypatch):
    """Tras listar opciones no se pregunta otra vez antes de elegir."""
    from app.agent import Agent
    from app.flows import media as media_flow
    from app.models import CatalogItem, Contact

    session.add(
        CatalogItem(
            sku="TAZA-1",
            name="Taza Cerámica Blanca 280ml",
            price=40,
            stock=6,
            brand="ALLEANZA",
            category="Tazas",
            active=True,
        )
    )
    contacto = Contact(wa_id="59170095001", phone_e164="+59170095001")
    session.add(contacto)
    await session.commit()

    async def _descarga(media_id):
        return (b"foto", "image/jpeg")

    async def _describe(archivo, mime):
        return {"objeto": "taza", "categoria": "Tazas", "marca": ""}

    monkeypatch.setattr(media_flow.media_service, "download", _descarga)
    monkeypatch.setattr(media_flow.vision, "describe", _describe)

    respuesta = await media_flow.reply(
        Agent(),
        session,
        contacto,
        {"media_id": "m1", "kind": "image"},
        "",
    )

    tipos = [m.kind for m in respuesta.messages]
    assert tipos.count("buttons") == 0
    assert tipos[-1] == "list"

def test_la_foto_no_ofrece_algo_que_solo_comparte_el_sustantivo():
    from app.flows.media import _coincide

    foto = {"objeto": "mochila", "atributos": "escolar, azul, acolchada"}

    assert not _coincide(
        foto, {"name": "MOCHILA PULVERIZADORA 16L INGCO", "category": "Fumigación"}
    )
    assert _coincide(
        foto, {"name": "Mochila Escolar Azul Acolchada", "category": "Mochilas"}
    )


def test_la_foto_sin_atributos_acepta_el_mismo_objeto():
    from app.flows.media import _coincide

    assert _coincide({"objeto": "taza"}, {"name": "Taza Cerámica", "category": "Tazas"})


async def test_elegir_un_producto_muestra_la_ficha(session, monkeypatch):
    """El guard de repetición no debe tapar el detalle que el cliente pidió."""
    from app.agent import Agent
    from app.models import CatalogItem, Contact

    session.add(
        CatalogItem(
            sku="FICHA-9",
            name="Mochila Pulverizadora 16L",
            price=279,
            stock=3,
            brand="INGCO",
            category="Fumigación",
            active=True,
        )
    )
    contacto = Contact(wa_id="59170096001", phone_e164="+59170096001")
    session.add(contacto)
    await session.commit()

    agente = Agent()
    for _ in range(2):
        respuesta = await agente.handle(session, contacto, "product:FICHA-9")
        respuesta = await agente.postprocess(
            session, contacto, "product:FICHA-9", respuesta
        )
        texto = " ".join(m.text or "" for m in respuesta.messages)
        assert "Precio" in texto or "Bs" in texto
        assert "ya te mostré" not in texto.lower()

def test_el_listado_muestra_el_descuento():
    from app.agent import Agent

    productos = [
        {
            "sku": "D-1",
            "name": "Aire Acondicionado 12000BTU",
            "price": "8000",
            "promo_price": "5719",
            "promo_discount_percent": "28.51",
            "brand": "LAKES",
            "category": "Aires",
        }
    ]

    mensajes = Agent._search_cards(productos)
    texto = mensajes[0].text or ""

    assert "(−29%)" in texto or "(−28%)" in texto
    assert "Bs 5,719.00" in texto.replace("5719.00", "5,719.00")

def test_la_foto_de_una_tele_encuentra_televisores():
    """En el catálogo se llaman «TV»: la foto dice «televisor»."""
    from app.flows.media import _coincide

    foto = {
        "objeto": "televisor",
        "atributos": "pantalla plana, color negro, google tv",
    }

    assert _coincide(foto, {"name": "TV 32 Smart LED HD Google TV", "category": "TV"})
    assert _coincide(
        foto, {"name": "Televisor Led 50 Pulgadas Samsung", "category": "TV"}
    )


def test_la_foto_de_un_taladro_inalambrico_encuentra_taladros():
    from app.flows.media import _coincide

    foto = {"objeto": "taladro inalámbrico", "atributos": "amarillo y negro"}

    assert _coincide(
        foto,
        {
            "name": "Taladro Atornillador 10mm 12v Bat Ingco",
            "category": "Herramientas",
        },
    )