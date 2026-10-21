"""Atajos deterministas: agregar por texto y confirmar el pago con "sí"."""

from __future__ import annotations

from app.agent import Agent
from app.models import Contact, Conversation, Message
from app.services import cart as cart_service


def _fail_if_llm(*args, **kwargs):  # pragma: no cover - sólo si se llama
    raise AssertionError("no debería usar el LLM")


async def test_agregar_por_texto_no_usa_llm(session):
    contact = Contact(wa_id="59170000801", phone_e164="+59170000801", name="Ana")
    session.add(contact)
    await session.commit()

    agent = Agent()
    agent._llm = _fail_if_llm  # type: ignore[method-assign]

    await agent.handle(session, contact, "agregar FILT-001 2")

    cart = await cart_service.get_or_create_cart(session, contact.id)
    items = await cart_service.items(session, cart)
    assert items and items[0].sku == "FILT-001"
    assert items[0].quantity == 2


async def test_si_tras_ofrecer_pago_cierra_pedido(session):
    contact = Contact(wa_id="59170000802", phone_e164="+59170000802", name="Ana")
    session.add(contact)
    await session.commit()

    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()
    session.add(
        Message(
            conversation_id=conversation.id,
            direction="out",
            text="¿Te genero el link/QR de pago?",
        )
    )
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 1)
    await session.commit()

    agent = Agent()
    agent._llm = _fail_if_llm  # type: ignore[method-assign]

    reply = await agent.handle(session, contact, "si, dale")

    text = " ".join(m.text for m in reply.messages)
    assert "Pedido" in text or "WA-" in text
    assert "link" in text.lower() or "qr" in text.lower()
