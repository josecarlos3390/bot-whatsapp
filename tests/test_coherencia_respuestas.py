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

async def test_saludo_con_presencia_no_busca(session):
    """«Hola hola, ¿estás ahí?» saludaba... y ofrecía estantes."""
    from app.models import CatalogItem

    for sku, nombre in (
        ("EST-1", "Estante Alto Merk Nogal"),
        ("EST-2", "Estante Esquinero Multiuso"),
    ):
        session.add(
            CatalogItem(
                sku=sku,
                name=nombre,
                price="839",
                stock=5,
                brand="TEST",
                category="Muebles",
                active=True,
            )
        )
    await session.commit()
    contacto = await _contacto(session, "59170084001")

    respuesta = await Agent().handle(session, contacto, "Hola hola estás ahí?")

    texto = " ".join(m.text or "" for m in respuesta.messages)
    assert "Rohi" in texto
    assert "Estante" not in texto
    assert respuesta.messages[0].kind == "buttons"


async def test_sigues_ahi_tambien_saluda(session):
    contacto = await _contacto(session, "59170084002")

    respuesta = await Agent().handle(session, contacto, "¿sigues ahí?")

    assert "Rohi" in (respuesta.messages[0].text or "")


async def test_saludo_con_producto_sigue_buscando(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="TAL-9",
            name="Taladro Percutor 13mm",
            price="500",
            stock=5,
            brand="INGCO",
            category="Herramientas",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170084003")

    respuesta = await Agent().handle(session, contacto, "hola, busco un taladro")

    texto = _todo(respuesta)
    assert "taladro" in texto.lower()
    assert "Soy *Rohi*" not in texto

async def test_no_busca_palabras_de_conversacion(session):
    """«estas ahi» y «hola» no deben traer productos por parecido."""
    from app.models import CatalogItem
    from app.services import catalog

    session.add_all(
        [
            CatalogItem(
                sku="EST-9",
                name="Estante Alto Merk",
                price="839",
                stock=5,
                category="Muebles",
                active=True,
            ),
            CatalogItem(
                sku="SIE-9",
                name="10 Sierras Bimetal",
                price="200",
                stock=5,
                category="Herramientas",
                active=True,
            ),
        ]
    )
    await session.commit()

    # "estas" ya no se convierte en "esta" + "estante".
    assert await catalog.search_items(session, "estas", limit=3) == []


async def test_pedir_una_persona_no_es_busqueda(session):
    contacto = await _contacto(session, "59170085001")

    respuesta = await Agent().handle(session, contacto, "hay alguien de soporte?")

    texto = respuesta.messages[0].text or ""
    assert "catálogo" not in texto.lower()
    assert "asesor" in texto.lower() or "equipo" in texto.lower()

async def test_finalizar_compra_por_texto(session, monkeypatch):
    """«Quiero finalizar la compra» debe ofrecer el cierre, no buscar."""
    from app.config import settings
    from app.models import CatalogItem
    from app.services import vtex_cart

    session.add(
        CatalogItem(
            sku="FIN-1",
            name="Producto Cierre",
            price="100",
            stock=5,
            brand="TEST",
            category="Pintura",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170086001")
    agente = Agent()

    monkeypatch.setattr(settings, "vtex_cart_enabled", False)
    await agente.handle(session, contacto, "add:FIN-1:1")

    monkeypatch.setattr(settings, "vtex_cart_enabled", True)
    monkeypatch.setattr(settings, "vtex_cart_via", "paas")
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.local")
    monkeypatch.setattr(settings, "sap_paas_api_key", "llave")
    monkeypatch.setattr(settings, "vtex_cart_pilot_phones", "")

    from app.services import cart as cart_service

    carrito = await cart_service.get_or_create_cart(session, contacto.id)
    carrito.vtex_cart_url = "https://rodabo.myvtex.com/checkout/?orderFormId=OF-9#/cart"
    await session.commit()

    async def _vigente(cart):
        return True

    monkeypatch.setattr(vtex_cart, "asegurar_vigente", _vigente)

    for frase in (
        "quiero finalizar la compra",
        "quiero cerrar mi pedido",
        "pasame el link de mi carrito",
        "quiero pagar",
    ):
        respuesta = await agente.handle(session, contacto, frase)
        assert respuesta.messages[0].kind == "cta", frase


async def test_preguntar_por_cuotas_no_cierra_el_pedido(session):
    contacto = await _contacto(session, "59170086002")

    respuesta = await Agent().handle(
        session, contacto, "se puede pagar en cuotas?"
    )

    assert respuesta.messages[0].kind != "cta"

async def test_la_confirmacion_de_agregado_es_detallada(session):
    """El mensaje de agregado muestra cantidad, precio y subtotal."""
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="EST-ELSA",
            name="Muñeca Elsa De Frozen",
            price="499",
            stock=9,
            brand="DISNEY",
            category="Juguetes",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170087001")

    respuesta = await Agent().handle(session, contacto, "add:EST-ELSA:2")
    mensaje = respuesta.messages[0]

    assert "¡Agregado a tu carrito!" in mensaje.text
    assert "Cantidad: 2 unidades" in mensaje.text
    assert "Precio unitario: Bs 499.00" in mensaje.text
    assert "Subtotal: Bs 998.00" in mensaje.text
    assert "Total del carrito" in mensaje.text
    titulos = [boton["title"] for boton in mensaje.buttons]
    assert titulos == ["Finalizar compra", "Seguir comprando", "Ver mi carrito"]


async def test_el_carrito_dice_cuantos_productos_y_unidades(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="CARR-1",
            name="Producto Carrito",
            price="100",
            stock=9,
            brand="TEST",
            category="Pintura",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170087002")
    agente = Agent()
    await agente.handle(session, contacto, "add:CARR-1:3")

    respuesta = await agente.handle(session, contacto, "carrito")
    texto = respuesta.messages[0].text

    assert "1 producto, 3 unidades" in texto
    assert "Total:" in texto