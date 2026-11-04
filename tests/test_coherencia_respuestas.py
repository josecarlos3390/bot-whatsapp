"""Las incoherencias que llegaron de chats reales no vuelven.

Cada caso salió de una conversación de prueba:

- «tienes muñecas?» respondido con «no tengo productos para munecas» (la ñ).
- «busco hot wheels» respondido con «no tengo hot wheels exactamente».
- «Quiero el auto a escala» abriendo la ficha de un estuche para autos.
- «Muéstrame el menú de opciones» respondido con «no tengo un menú».
"""

from __future__ import annotations

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app.services import coherencia


async def _contacto(session, wa_id: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}", name="Prueba")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def _juguetes(session):
    datos = [
        ("HW-1", "Set 10 Autos A Escala Hot Wheels", "399", "HOT WHEELS"),
        ("HW-2", "Estuche Para Autos 8 Unidades Hot Wheels", "129", "HOT WHEELS"),
        ("HW-3", "Pista Accion De Turbina Hot Wheels", "559", "HOT WHEELS"),
        ("MU-1", "Muñeca Bebe Princesas Disney", "299", "DISNEY"),
        ("MU-2", "Muñeca Bebe Lloron Tiny Cuddles", "449", "CRY BABIES"),
        ("PE-1", "Peluche Clasico Alien 25Cm", "199", "DISNEY"),
        ("ES-1", "Auto A Escala Avengers Todo Terreno", "199", "MARVEL"),
        ("ES-2", "Auto A Escala Batman Todo Terreno", "199", "DC"),
        ("ES-3", "Auto A Escala Spiderman Todo Terreno", "199", "MARVEL"),
    ]
    for sku, nombre, precio, marca in datos:
        session.add(
            CatalogItem(
                sku=sku,
                name=nombre,
                price=precio,
                stock=22,
                brand=marca,
                category="Vehículos",
                active=True,
            )
        )
    await session.commit()


def _todo(respuesta) -> str:
    return " ".join(
        (m.text or "") + str(m.sections or "") for m in respuesta.messages
    )


async def test_no_niega_algo_que_tiene(session):
    """Si el catálogo tiene muñecas, no puede decir que no tiene."""
    await _juguetes(session)
    contacto = await _contacto(session, "59170080001")

    respuesta = await Agent().handle(session, contacto, "tienes muñecas?")
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert not coherencia.niega_tenencia(texto)
    assert "Muñeca" in _todo(respuesta)


async def test_no_niega_hot_wheels(session):
    await _juguetes(session)
    contacto = await _contacto(session, "59170080002")

    respuesta = await Agent().handle(session, contacto, "busco hot wheels")

    assert not coherencia.niega_tenencia(
        " ".join(m.text or "" for m in respuesta.messages)
    )
    assert "Hot Wheels" in _todo(respuesta)


async def test_muneca_sin_enie_tambien_la_encuentra(session):
    """La ñ no puede romper la búsqueda."""
    await _juguetes(session)
    contacto = await _contacto(session, "59170080003")

    respuesta = await Agent().handle(session, contacto, "tienes munecas?")

    assert "Muñeca" in _todo(respuesta)


async def test_no_abre_la_ficha_de_un_producto_ajeno(session):
    """«el auto a escala» no es el estuche para autos."""
    from types import SimpleNamespace

    await _juguetes(session)
    contacto = await _contacto(session, "59170080004")
    agente = Agent()
    llamada = SimpleNamespace(
        function=SimpleNamespace(
            name="get_product", arguments='{"sku": "HW-2"}'
        )
    )

    # Con un mensaje que sí habla del estuche, la ficha se muestra.
    propio = await agente._direct_reply_for_tool(
        session, contacto, llamada, "quiero el estuche para autos"
    )
    assert propio is not None

    # Con un mensaje de autos a escala, se busca en vez de abrir el estuche.
    ajeno = await agente._direct_reply_for_tool(
        session, contacto, llamada, "quiero el auto a escala"
    )
    assert ajeno is not None
    assert not any(m.kind == "image" for m in ajeno.messages)
    assert "Auto A Escala" in _todo(ajeno)


async def test_el_menu_se_entiende(session):
    await _juguetes(session)
    contacto = await _contacto(session, "59170080005")

    respuesta = await Agent().handle(
        session, contacto, "Muéstrame el menú de opciones"
    )
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "no tengo un menú" not in texto
    assert respuesta.messages[0].kind == "buttons"


def test_el_detector_marca_las_negaciones_reales():
    assert coherencia.niega_tenencia("No tengo *hot wheels* exactamente")
    assert not coherencia.niega_tenencia("Esto es lo que tengo de hot wheels")


def test_la_ficha_ajena_se_detecta():
    aviso = coherencia.ficha_ajena(
        "quiero el auto a escala", "Estuche Para Autos 8 Unidades Hot Wheels"
    )

    assert aviso is not None
    assert "escala" in aviso["faltan"]


def test_una_ficha_coherente_no_se_marca():
    assert (
        coherencia.ficha_ajena(
            "quiero el auto a escala", "Auto A Escala Batman"
        )
        is None
    )


async def test_la_ficha_muestra_el_codigo_sap(session):
    """La ficha lleva el código de SAP Business One (el RefId de VTEX)."""
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="LBLELEC020078",
            name="Cafetera Express 1465W 20Bar Inox Cecotec",
            price="1599",
            stock=10,
            brand="CECOTEC",
            category="Cafeteras",
            barcode="8435484019866",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170081001")

    respuesta = await Agent().handle(
        session, contacto, "product:LBLELEC020078"
    )
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "Código SAP: LBLELEC020078" in texto
    assert "8435484019866" in texto

async def test_autos_a_escala_no_muestra_munecas(session):
    """El bug del chat: tras el regalo para chicos, "autos a escala" salió con muñecas."""
    from app.models import CatalogItem

    datos = [
        ("AUT-1", "Auto A Escala Avengers Todo Terreno A Friccion", "199", "MARVEL"),
        ("AUT-2", "Auto A Escala Batman Todo Terreno A Friccion", "199", "DC"),
        ("AUT-3", "Auto A Escala Spiderman Todo Terreno A Friccion", "199", "MARVEL"),
        ("MUN-1", "Muñeca Bebe Princesas Disney", "299", "DISNEY"),
        ("MUN-2", "Muñeca Bebe Lloron Tiny Cuddles", "449", "CRY BABIES"),
    ]
    for sku, nombre, precio, marca in datos:
        session.add(
            CatalogItem(
                sku=sku,
                name=nombre,
                price=precio,
                stock=20,
                brand=marca,
                category="Vehículos",
                active=True,
            )
        )
    await session.commit()

    contacto = await _contacto(session, "59170082001")
    agente = Agent()
    await agente.handle(session, contacto, "quiero comprar algo para mis hijos")
    await agente.handle(session, contacto, "kidsage:6-9")

    respuesta = await agente.handle(session, contacto, "Autos a escala")
    texto = _todo(respuesta)

    assert "Auto A Escala" in texto
    assert "Muñeca" not in texto


async def test_kidsage_es_una_accion():
    from app.services import actions

    assert actions.es_accion("kidsage:6-9")

async def test_el_mensaje_nuevo_gana_al_rubro_anterior(session):
    """Tras ver muñecas, "autos a escala" no puede heredar el rubro."""
    from app.models import CatalogItem

    for sku, nombre, marca in (
        ("MK-1", "Muñeca Bebe Princesas", "DISNEY"),
        ("MK-2", "Muñeca Bebe Lloron", "CRY BABIES"),
        ("MC-1", "Auto A Escala Avengers A Friccion", "MARVEL"),
        ("MC-2", "Auto A Escala Batman A Friccion", "DC"),
        ("MC-3", "Auto A Escala Spiderman A Friccion", "MARVEL"),
    ):
        session.add(
            CatalogItem(
                sku=sku,
                name=nombre,
                price="199",
                stock=20,
                brand=marca,
                category="Vehículos",
                active=True,
            )
        )
    await session.commit()
    contacto = await _contacto(session, "59170083001")
    agente = Agent()

    await agente.handle(session, contacto, "tienes muñecas?")
    respuesta = await agente.handle(session, contacto, "autos a escala")

    texto = _todo(respuesta)
    assert "Auto A Escala" in texto
    assert "Muñeca" not in texto


async def test_reconoce_la_queja_por_la_lista_anterior():
    from app.services import pedido_vago

    assert pedido_vago.es_cuestionamiento(
        "Primero me dijiste que tenías 5 opciones y luego 3?"
    )
    assert pedido_vago.es_cuestionamiento(
        "Me diste la lista de unas muñecas no son autos a escala"
    )
    assert not pedido_vago.es_cuestionamiento("hola, busco un taladro")