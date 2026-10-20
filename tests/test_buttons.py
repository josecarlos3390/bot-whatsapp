from __future__ import annotations

from app.agent import Agent
from app.models import Contact
from app.whatsapp import Outbound, WhatsAppClient


async def test_greeting_returns_quick_actions(session):
    contact = Contact(wa_id="59170000777", phone_e164="+59170000777")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "Hola que tal..!!")
    assert reply.messages[0].kind == "buttons"
    ids = [button["id"] for button in reply.messages[0].buttons]
    assert ids == ["explore", "human"]

    catalog = await Agent().handle(session, contact, "Tienes catálogo?")
    assert catalog.messages[0].kind == "list"


async def test_cart_button_returns_cart(session):
    contact = Contact(wa_id="59170000778", phone_e164="+59170000778")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "cart")
    assert "carrito" in reply.messages[0].text.lower()
    assert reply.messages[0].kind == "buttons"


def test_list_payload():
    client = WhatsAppClient()
    payload = client._payload(
        "59170000000",
        Outbound(
            kind="list",
            text="Elegí una categoría",
            button_text="Ver categorías",
            sections=[
                {
                    "title": "Ambientes",
                    "rows": [
                        {"id": "cat:sala", "title": "Sala"},
                        {"id": "cat:cocina", "title": "Cocina"},
                    ],
                }
            ],
        ),
    )
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"]["button"] == "Ver categorías"


async def test_category_list_and_product_detail(session):
    contact = Contact(wa_id="59170000779", phone_e164="+59170000779")
    session.add(contact)
    await session.commit()
    agent = Agent()

    categories = await agent.handle(session, contact, "catalog")
    assert categories.messages[0].kind == "list"
    rows = categories.messages[0].sections[0]["rows"]
    assert rows and any(row["id"].startswith("cat:") for row in rows)

    products = await agent.handle(session, contact, "cat:Filtros")
    assert products.messages[0].kind == "list"
    product_rows = products.messages[0].sections[0]["rows"]
    assert any(row["id"] == "product:FILT-001" for row in product_rows)

    detail = await agent.handle(session, contact, "product:FILT-001")
    buttons_message = next(
        message for message in detail.messages if message.kind == "buttons"
    )
    assert "FILT-001" not in buttons_message.text
    assert any(
        button["id"].startswith("add:FILT-001")
        for button in buttons_message.buttons
    )


async def test_checkout_intent_does_not_handoff(session):
    contact = Contact(wa_id="59170000790", phone_e164="+59170000790")
    session.add(contact)
    await session.commit()
    agent = Agent()
    added = await agent.handle(session, contact, "add:FILT-001:1")
    assert added.messages

    reply = await agent.handle(session, contact, "confirma el pedido")
    text = "\n".join(message.text for message in reply.messages)
    assert "Pedido" in text
    assert "deriv" not in text.lower()


async def test_clear_cart_intent(session):
    contact = Contact(wa_id="59170000792", phone_e164="+59170000792")
    session.add(contact)
    await session.commit()
    agent = Agent()
    await agent.handle(session, contact, "add:FILT-001:1")

    reply = await agent.handle(session, contact, "vacía mi carrito")
    assert any("vacié" in message.text.lower() for message in reply.messages)
    cart = await agent.handle(session, contact, "cart")
    assert "vacío" in cart.messages[0].text.lower()


async def test_checkout_failure_is_explained(session, monkeypatch):
    contact = Contact(wa_id="59170000791", phone_e164="+59170000791")
    session.add(contact)
    await session.commit()
    agent = Agent()
    await agent.handle(session, contact, "add:FILT-001:1")

    async def boom(self):
        raise RuntimeError("SAP no disponible")

    from app.agent import Toolbox

    monkeypatch.setattr(Toolbox, "tool_checkout", boom)
    reply = await agent.handle(session, contact, "confirma el pedido")
    text = "\n".join(message.text for message in reply.messages)
    assert "no pude cerrar el pedido" in text.lower()
    assert "problema procesando" not in text
