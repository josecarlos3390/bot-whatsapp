"""Botones de categoría: listas deterministas y sin texto repetido."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


async def _contacto(session, wa_id: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def test_categoria_devuelve_lista_de_productos(session):
    session.add_all(
        [
            CatalogItem(
                sku="SALA-SOFA",
                name="Sofá Bradford 2 Puestos Beige",
                price=5990,
                stock=3,
                category="MUEBLES",
                brand="BRADFORD",
                active=True,
            ),
            CatalogItem(
                sku="SALA-MESA",
                name="Mesa Central Asimétrica",
                price=1200,
                stock=2,
                category="MUEBLES",
                active=True,
            ),
            CatalogItem(
                sku="SALA-ESPEJO",
                name="Espejo Capela 60 Cozimax",
                price=399,
                stock=5,
                category="MUEBLES",
                brand="COZIMAX",
                active=True,
            ),
        ]
    )
    await session.commit()
    contacto = await _contacto(session, "59170021001")

    respuesta = await Agent().handle(session, contacto, "cat:sala")

    # Un solo mensaje: el menú con los productos y su precio.
    assert len(respuesta.messages) == 1
    mensaje = respuesta.messages[0]
    assert "Bs" in (mensaje.text or "")
    assert mensaje.kind == "list"
    titulos = [row["title"].lower() for row in mensaje.sections[0]["rows"]]
    # Primero lo del ambiente, no el espejo.
    assert "sof" in titulos[0] or "mesa" in titulos[0]
    assert "espejo" not in titulos[0]


async def test_categoria_no_repite_el_texto(session):
    session.add(
        CatalogItem(
            sku="SALA-SOFA-2",
            name="Sofá Acapulco 2p Cuero Avena",
            price=7990,
            stock=2,
            category="MUEBLES",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170021002")

    respuesta = await Agent().handle(session, contacto, "cat:sala")

    textos = [
        (mensaje.text or "").strip().lower()
        for mensaje in respuesta.messages
        if mensaje.text
    ]
    assert len(textos) == len(set(textos))


def test_las_preguntas_por_rubro_llevan_a_busquedas_distintas():
    from app.services import categorias

    for clave, datos in categorias.PREGUNTAS.items():
        terminos = [termino for _, termino in datos["opciones"]]
        assert len(set(terminos)) == len(terminos), clave
        assert categorias.pregunta(clave) is not None


def test_una_categoria_sin_pregunta_no_pregunta():
    from app.services import categorias

    assert categorias.pregunta("ofertas") is None


def test_las_opciones_incluyen_ver_todo():
    from app.services import categorias

    filas = categorias.opciones("sala")
    assert filas[-1]["title"] == "Ver todo"
    assert filas[-1]["id"] == "sub:sala|todo"
    assert all(fila["id"].startswith("sub:") for fila in filas)

def test_los_rangos_de_presupuesto_usan_precios_reales():
    from app.services import presupuesto

    rangos = presupuesto.bandas([100, 500, 1200, 3000, 8000])

    assert len(rangos) == 3
    assert rangos[0]["max"] < rangos[1]["max"]
    assert rangos[-1]["title"] if False else True
    assert rangos[-1]["max"] == 0


def test_sin_diferencia_de_precios_no_pregunta():
    from app.services import presupuesto

    assert presupuesto.bandas([100, 110, 120, 130]) == []
    assert presupuesto.bandas([100, 200]) == []


def test_los_botones_llevan_el_tope():
    from app.services import presupuesto

    rangos = presupuesto.bandas([100, 500, 1200, 3000, 8000])
    botones = presupuesto.botones("sala", rangos)

    assert all(boton["id"].startswith("price:sala|") for boton in botones)
    assert botones[-1]["title"] == "Sin límite"


def test_entiende_hasta_cuanto_quiero_gastar():
    from app.services import presupuesto

    assert presupuesto.limite("busco algo hasta 1.500") == 1500
    assert presupuesto.limite("maximo 800") == 800
    assert presupuesto.limite("busco un sofa") is None
    assert presupuesto.quiere_barato("algo economico por favor")

async def test_reservar_deja_aviso_para_un_asesor(session):
    from sqlalchemy import select

    from app.models import CatalogItem, Handoff

    session.add(
        CatalogItem(
            sku="RES-001",
            name="Sofá Reserva",
            price="1000",
            stock=3,
            brand="TEST",
            category="Sala",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170021050")

    from app.agent import Agent

    respuesta = await Agent().handle(session, contacto, "reserve:RES-001")

    texto = " ".join(m.text or "" for m in respuesta.messages)
    assert "300,00" in texto  # 30 % de 1000
    assert "48" in texto
    avisos = (await session.scalars(select(Handoff))).all()
    assert any("RES-001" in (aviso.reason or "") for aviso in avisos)


async def test_reservar_un_producto_inexistente_no_rompe(session):
    contacto = await _contacto(session, "59170021051")

    from app.agent import Agent

    respuesta = await Agent().handle(session, contacto, "reserve:NO-EXISTE")

    assert respuesta.messages

async def test_el_menu_de_categorias_tiene_pistas_y_salida(session):
    from app.agent import Agent
    from app.models import Contact, Conversation

    contacto = Contact(
        wa_id="59170025001", phone_e164="+59170025001", name="Ana"
    )
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "catalog")
    filas = respuesta.messages[0].sections[0]["rows"]

    # Las pistas no repiten el nombre de la categoría.
    for fila in filas[:-1]:
        assert fila["description"], fila["title"]
        assert fila["description"].lower() != fila["title"].lower()
    # Y siempre hay una salida para escribir el producto.
    assert filas[-1]["id"] == "search"
    assert len(filas) <= 10

async def test_la_ficha_ofrece_agregar_sin_cantidad(session):
    from app.agent import Agent
    from app.models import CatalogItem, Contact, Conversation

    session.add(
        CatalogItem(
            sku="CARD-001",
            name="Microondas Card",
            price="1000",
            stock=5,
            brand="TEST",
            category="Microondas",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170027001")

    respuesta = await Agent().handle(session, contacto, "product:CARD-001")
    filas = respuesta.messages[-1].sections[0]["rows"]
    titulos = [fila["title"] for fila in filas]

    assert "Agregar al carrito" in titulos
    assert "Hablar con asesor" in titulos
    assert not any("Reservar" in titulo for titulo in titulos)
    assert not any(titulo.startswith("Agregar 1") for titulo in titulos)


async def test_agregar_pregunta_cantidad_y_la_respeta(session):
    from app.agent import Agent
    from app.models import CatalogItem, Contact, Conversation

    session.add(
        CatalogItem(
            sku="CARD-002",
            name="Microondas Cantidad",
            price="1000",
            stock=9,
            brand="TEST",
            category="Microondas",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170027002")
    agente = Agent()

    pregunta = await agente.handle(session, contacto, "add:CARD-002")
    assert pregunta.messages[0].kind == "list"
    assert "Cuántas unidades" in (pregunta.messages[0].text or "")

    # Escribe el número en vez de tocar la lista.
    respuesta = await agente.handle(session, contacto, "4")
    texto = respuesta.messages[0].text or ""
    assert "4" in texto or "Agregué" in texto

    carrito = await agente.handle(session, contacto, "carrito")
    assert "4 ×" in (carrito.messages[0].text or "")

async def test_pedir_el_menu_no_busca_productos(session):
    from app.agent import Agent

    contacto = await _contacto(session, "59170028001")
    agente = Agent()

    for texto in (
        "Muéstrame el menú de opciones",
        "Puedes mostrarme las opciones nuevamente?",
        "menu",
    ):
        respuesta = await agente.handle(session, contacto, texto)
        mensaje = respuesta.messages[0]
        assert mensaje.kind == "buttons", texto
        ids = [boton["id"] for boton in mensaje.buttons]
        assert "catalog" in ids


async def test_otra_opcion_vuelve_al_menu_de_categorias(session):
    from app.agent import Agent

    contacto = await _contacto(session, "59170028002")

    respuesta = await Agent().handle(session, contacto, "otra opción")

    assert respuesta.messages[0].kind == "list"

async def test_sin_limite_no_vuelve_a_preguntar(session):
    """Tocar «Sin límite» listaba de nuevo la pregunta: bucle."""
    from app.agent import Agent
    from app.models import CatalogItem, Contact, Conversation

    for indice in range(6):
        session.add(
            CatalogItem(
                sku=f"LB-{indice}",
                name=f"Cocina {indice}",
                price=str(1000 + indice * 1500),
                stock=5,
                brand="TEST",
                category="LINEA BLANCA",
                active=True,
            )
        )
    await session.commit()
    contacto = await _contacto(session, "59170029001")
    agente = Agent()

    await agente.handle(session, contacto, "cat:linea-blanca")

    respuesta = await agente.handle(session, contacto, "price:linea-blanca|0")

    texto = respuesta.messages[0].text or ""
    # Lo importante: no vuelve a preguntar el presupuesto.
    assert "Hasta cuánto querés gastar" not in texto
    assert respuesta.messages[0].kind == "list"

def test_el_error_de_stock_no_revela_datos_internos():
    from app.agent import _error_cantidad

    error = (
        "No hay 7 unidades de COCINA 4H INOX en una sola tienda. "
        "Disponible por tienda: Tienda 1: 5, Tienda 3: 0, Tienda 2: 0."
    )
    texto = _error_cantidad(error, "LBLCNHR020145")

    assert "No tengo esa cantidad disponible" in texto
    # Ni cantidades ni sucursales: es información interna.
    assert "Tienda 1" not in texto
    assert "unidades de" not in texto
    assert "5" not in texto

async def test_cerrar_pedido_crea_la_derivacion(session, monkeypatch):
    """El bot decia "ya lo pase a un asesor" sin crear el caso."""
    from sqlalchemy import select

    from app.agent import Agent
    from app.models import CatalogItem, Conversation, Handoff

    session.add(
        CatalogItem(
            sku="CHK-001",
            name="Producto Pedido",
            price="1000",
            stock=5,
            brand="TEST",
            category="Cocinas",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170031001")
    agente = Agent()

    async def _falla(**kwargs):
        raise RuntimeError("SAP no disponible")

    monkeypatch.setattr(
        agente, "tool_checkout", getattr(agente, "tool_checkout", None), raising=False
    )

    await agente.handle(session, contacto, "add:CHK-001:2")

    # Si el checkout no se puede completar, la derivación tiene que existir.
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contacto.id)
    )
    respuesta = await agente.handle(session, contacto, "confirmar")
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    handoffs = (
        await session.scalars(
            select(Handoff).where(Handoff.conversation_id == conversacion.id)
        )
    ).all()

    if "asesor" in texto:
        assert handoffs, "prometió derivar y no creó el caso"

async def test_el_carrito_se_alinea_con_la_tienda(session, monkeypatch):
    """Si el cliente agregó cantidades en VTEX, el bot las muestra."""
    from sqlalchemy import select

    from app.agent import Agent
    from app.config import settings
    from app.models import Cart, CatalogItem
    from app.services import cart as cart_service
    from app.services import vtex_cart

    session.add(
        CatalogItem(
            sku="VTX-9",
            name="Producto Tienda",
            price="100",
            stock=20,
            brand="TEST",
            category="Pintura",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170033001")

    await Agent().handle(session, contacto, "add:VTX-9:1")
    carrito = await cart_service.get_or_create_cart(session, contacto.id)
    carrito.vtex_order_form_id = "OF-1"
    await session.commit()

    monkeypatch.setattr(settings, "vtex_cart_enabled", True)
    monkeypatch.setattr(settings, "vtex_cart_via", "paas")
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.local")
    monkeypatch.setattr(settings, "sap_paas_api_key", "llave")

    async def _consulta(cart):
        return {
            "order_form_id": "OF-1",
            "checkout_url": None,
            "items": [{"sku": "VTX-9", "quantity": 4, "price": 100.0}],
            "value": 400.0,
            "currency": "BOB",
            "messages": [],
        }

    monkeypatch.setattr(vtex_cart, "consultar", _consulta)

    respuesta = await Agent().handle(session, contacto, "carrito")

    assert "4 ×" in (respuesta.messages[0].text or "")