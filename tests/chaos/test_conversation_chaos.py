"""Pruebas de caos: conversación, reglas, stock y fallas técnicas."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agent import Agent, AgentReply, Outbound, Toolbox
from app.models import CatalogItem, Contact, Conversation
from app.services import area_rules, conversation_guard, recommendations
from sqlalchemy import select


async def _contact(session, wa_id: str = "59170009000") -> Contact:
    contact = await session.scalar(
        select(Contact).where(Contact.wa_id == wa_id)
    )
    if contact is None:
        contact = Contact(
            wa_id=wa_id,
            phone_e164=f"+{wa_id}",
            name="Prueba Caos",
        )
        session.add(contact)
        await session.flush()
    conversation = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversation is None:
        session.add(Conversation(contact_id=contact.id))
    await session.commit()
    return contact


def _item(
    sku: str,
    name: str,
    *,
    brand: str,
    price: float,
    stock: int,
    category: str = "Filtros",
) -> CatalogItem:
    return CatalogItem(
        sku=sku,
        name=name,
        description=name,
        category=category,
        brand=brand,
        price=price,
        currency="BOB",
        stock=stock,
        active=True,
        sap_valid=True,
    )


async def test_sin_respuesta_no_deja_silencio(session):
    contact = await _contact(session, "59170009001")
    agent = Agent()
    reply = await agent.postprocess(
        session, contact, "mensaje raro", AgentReply([])
    )
    assert reply.messages
    assert reply.messages[0].text
    assert "producto" in reply.messages[0].text.lower()


async def test_pregunta_pendiente_de_medida(session):
    contact = await _contact(session, "59170009002")
    session.add_all(
        [
            _item(
                "COL-2P",
                "COLCHON TEST 2 PLAZAS 140X190",
                brand="TEST",
                price=1000,
                stock=5,
                category="Colchones",
            ),
            _item(
                "COL-1P",
                "COLCHON TEST 1 PLAZA 100X190",
                brand="TEST",
                price=800,
                stock=5,
                category="Colchones",
            ),
        ]
    )
    await session.commit()
    await conversation_guard.set_pending(
        session,
        contact,
        slot="size",
        question="¿Qué medida te sirve?",
        query="colchon",
    )
    reply = await Agent().handle(session, contact, "2 plazas", [], None)
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "2 PLAZAS" in text.upper()
    assert "100X190" not in text


async def test_referencia_el_primero(session):
    contact = await _contact(session, "59170009003")
    session.add_all(
        [
            _item(
                "REF-1",
                "FILTRO PRIMERO TEST",
                brand="WIX",
                price=100,
                stock=5,
            ),
            _item(
                "REF-2",
                "FILTRO SEGUNDO TEST",
                brand="BOSCH",
                price=120,
                stock=5,
            ),
        ]
    )
    await session.commit()
    await recommendations.save(
        session,
        contact.id,
        query="filtro",
        category="Filtros",
        brand=None,
        size=None,
        min_price=None,
        max_price=None,
        products=[
            {"sku": "REF-1", "name": "FILTRO PRIMERO TEST", "brand": "WIX", "price": "100", "stock": 5},
            {"sku": "REF-2", "name": "FILTRO SEGUNDO TEST", "brand": "BOSCH", "price": "120", "stock": 5},
        ],
    )
    reply = await Agent().postprocess(
        session,
        contact,
        "filtro",
        AgentReply([Outbound(text="Te muestro estas opciones.")]),
    )
    assert reply.messages
    reply = await Agent().handle(session, contact, "el primero", [], None)
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "FILTRO PRIMERO TEST" in text
    assert "FILTRO SEGUNDO TEST" not in text


async def test_detector_de_bucle(session):
    contact = await _contact(session, "59170009004")
    agent = Agent()
    reply = AgentReply([Outbound(text="Respuesta idéntica de prueba")])
    first = await agent.postprocess(session, contact, "hola", reply)
    second = await agent.postprocess(session, contact, "hola", reply)
    assert first.messages[0].text == "Respuesta idéntica de prueba"
    assert "No quiero repetirte" in second.messages[0].text


async def test_stock_suficiente_para_cantidad(session):
    contact = await _contact(session, "59170009005")
    session.add_all(
        [
            _item(
                "QTY-2",
                "CAOSQTY DOS",
                brand="WIX",
                price=100,
                stock=2,
                category="CaosQty",
            ),
            _item(
                "QTY-5",
                "CAOSQTY CINCO",
                brand="BOSCH",
                price=120,
                stock=5,
                category="CaosQty",
            ),
        ]
    )
    await session.commit()
    result = await Toolbox(session, contact, None).tool_search_products(
        query="caosqty", quantity=3, limit=5
    )
    skus = {product["sku"] for product in result["products"]}
    assert skus == {"QTY-5"}
    assert result["quantity_shortfall"] == 0


async def test_stock_insuficiente_no_ofrece(session):
    contact = await _contact(session, "59170009006")
    session.add(
        _item(
            "QTY-2",
            "CAOSQTY DOS",
            brand="WIX",
            price=100,
            stock=2,
            category="CaosQty",
        )
    )
    await session.commit()
    result = await Toolbox(session, contact, None).tool_search_products(
        query="caosqty", quantity=3, limit=5
    )
    assert result["products"] == []
    assert result["quantity_shortfall"] == 3


async def test_regla_de_marca_ordena_primero(session):
    contact = await _contact(session, "59170009007")
    session.add_all(
        [
            _item("RULE-A", "FILTRO RULE A", brand="BOSCH", price=100, stock=5),
            _item("RULE-B", "FILTRO RULE B", brand="WIX", price=100, stock=5),
            _item("RULE-C", "FILTRO RULE C", brand="MANN", price=100, stock=5),
        ]
    )
    await session.commit()
    rule = await area_rules.create_rule(
        session,
        area="ecommerce",
        name="Caos: priorizar WIX",
        rule_type="brand_priority",
        condition={"category": "filtro"},
        action={"brand": "WIX"},
        priority=100,
        status="published",
        changed_by="test",
    )
    try:
        result = await Toolbox(session, contact, None).tool_search_products(
            query="filtro", limit=5
        )
        assert result["products"][0]["brand"] == "WIX"
        assert len(result["products"]) >= 3
    finally:
        await area_rules.delete_rule(session, rule)


async def test_falla_del_llm_no_deja_silencio(session, monkeypatch):
    contact = await _contact(session, "59170009008")
    agent = Agent()

    async def boom(*args, **kwargs):
        raise RuntimeError("falla simulada del LLM")

    monkeypatch.setattr(agent, "_llm_handle", boom)
    reply = await agent.handle(
        session, contact, "háblame de algo raro", [], None
    )
    reply = await agent.postprocess(
        session, contact, "háblame de algo raro", reply
    )
    assert reply.messages
    assert any(message.text for message in reply.messages)


async def test_respuesta_sin_stock(session):
    contact = await _contact(session, "59170009009")
    session.add(_item("NOSTOCK", "FILTRO SIN STOCK", brand="WIX", price=100, stock=5))
    await session.commit()
    reply = await Agent()._search_reply(session, contact, "filtro")
    text = "\n".join(message.text or "" for message in reply.messages)
    assert text
    assert "stock" not in text.lower()


async def test_halloween_no_recomienda_muebles(session):
    contact = await _contact(session, "59170009010")
    reply = await Agent().handle(
        session, contact, "tienes algo para halloween", [], None
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "halloween" in text.lower()
    assert "mueble" not in text.lower()
    assert text.strip()


async def test_vacaciones_no_pide_historial(session):
    contact = await _contact(session, "59170009012")
    session.add(
        _item(
            "VAC-TV",
            "TELEVISOR PARA VACACIONES TEST",
            brand="TEST",
            price=2000,
            stock=3,
            category="TV",
        )
    )
    await session.commit()
    reply = await Agent().handle(
        session,
        contact,
        "voy a salir de vacaciones, que puedo comprar para entretenerme",
        [],
        None,
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "CI o NIT" not in text
    assert "TELEVISOR PARA VACACIONES" in text.upper()


async def test_mis_compras_si_pide_identificacion(session):
    contact = await _contact(session, "59170009013")
    reply = await Agent().handle(
        session, contact, "quiero ver mis compras", [], None
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "CI o NIT" in text


async def test_expansion_semantica_valida_contra_catalogo(session):
    contact = await _contact(session, "59170009011")
    session.add(
        _item(
            "CAOS-REGALO",
            "CAOSREGALO VELA DE PRUEBA",
            brand="TEST",
            price=50,
            stock=4,
            category="Caos",
        )
    )
    await session.commit()

    class FakeCompletions:
        async def create(self, **kwargs):
            content = json.dumps(
                {
                    "intent": "ocasion",
                    "related_terms": ["caosregalo"],
                    "adjacent_terms": [],
                    "exclusions": [],
                }
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )

    agent = Agent()
    agent._llm = lambda: SimpleNamespace(  # type: ignore[method-assign]
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    reply = await agent.handle(
        session, contact, "tienes algo para caosregalo", [], None
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "CAOSREGALO" in text
    assert "stock" not in text.lower()


async def test_estado_ambiguo_pregunta_antes_de_responder(session):
    contact = await _contact(session, "59170009015")
    reply = await Agent().handle(session, contact, "¿Cuál es el estado?", [], None)
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "estado del pedido" in text
    assert "estado de un producto" in text
    guard = await conversation_guard.get_for_contact(session, contact)
    assert guard is not None
    assert guard.pending_slot == "intent"


async def test_estado_de_pedido_no_es_ambiguo(session):
    contact = await _contact(session, "59170009016")
    reply = await Agent().handle(
        session, contact, "¿Cuál es el estado de mi pedido?", [], None
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "ID del pedido" in text
    guard = await conversation_guard.get_for_contact(session, contact)
    assert guard is None or guard.pending_slot != "intent"


async def test_si_no_infiere_pregunta_y_guarda_tema(session):
    contact = await _contact(session, "59170009014")

    class FakeCompletions:
        async def create(self, **kwargs):
            content = json.dumps(
                {
                    "intent": "tema",
                    "related_terms": ["zzzsinresultado"],
                    "adjacent_terms": ["zzzsinresultado"],
                    "exclusions": [],
                }
            )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )

    agent = Agent()
    agent._llm = lambda: SimpleNamespace(  # type: ignore[method-assign]
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    reply = await agent.handle(
        session, contact, "tienes algo para zzzsinresultado", [], None
    )
    text = "\n".join(message.text or "" for message in reply.messages)
    assert "?" in text
    guard = await conversation_guard.get_for_contact(session, contact)
    assert guard is not None
    assert guard.pending_slot == "topic"



