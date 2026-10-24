"""Charla nueva dentro del mismo chat: se conserva el historial, no el rubro."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation, ConversationState
from app.services import conversation_state, session_flow


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _preparar(session, wa_id: str, *, horas: float, rubro: str):
    contact = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contact)
    await session.flush()
    conversation = Conversation(
        contact_id=contact.id,
        last_message_at=_ahora() - timedelta(hours=horas),
    )
    session.add(conversation)
    await session.flush()
    session.add(
        ConversationState(
            conversation_id=conversation.id,
            category=rubro,
            brand="LG",
            size="55",
            last_sku="TV-55",
        )
    )
    session.add(
        CatalogItem(
            sku="COLCH-TEST",
            name="Colchón Test 2 Plazas",
            price=1000,
            stock=3,
            category="Colchones",
            active=True,
        )
    )
    await session.commit()
    return contact, conversation


async def test_pausa_larga_reinicia_el_contexto(session):
    contact, conversation = await _preparar(
        session, "59170001401", horas=8, rubro="TV"
    )

    info = await session_flow.start_new_if_needed(
        session, conversation, contact
    )

    assert info["new"] is True
    assert info["gap_minutes"] >= 7 * 60
    estado = await conversation_state.get_state(session, conversation.id)
    assert estado.category is None
    assert estado.brand is None
    assert estado.size is None
    assert estado.last_sku is None


async def test_pausa_corta_conserva_el_contexto(session):
    contact, conversation = await _preparar(
        session, "59170001402", horas=0.1, rubro="TV"
    )

    info = await session_flow.start_new_if_needed(
        session, conversation, contact
    )

    assert info["new"] is False
    estado = await conversation_state.get_state(session, conversation.id)
    assert estado.category == "TV"


async def test_saludo_tras_pausa_empieza_de_nuevo(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact, _conversation = await _preparar(
        session, "59170001403", horas=9, rubro="TV"
    )

    reply = await Agent().handle(session, contact, "hola")

    texto = " ".join(message.text or "" for message in reply.messages).lower()
    assert "rohi" in texto
    estado = await conversation_state.get_state(session, _conversation.id)
    assert estado.category is None


async def test_despedida_cierra_y_limpia_el_contexto(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact, conversation = await _preparar(
        session, "59170001404", horas=0.05, rubro="TV"
    )

    reply = await Agent().handle(session, contact, "gracias, hasta luego")

    texto = " ".join(message.text or "" for message in reply.messages).lower()
    assert "gracias a vos" in texto
    estado = await conversation_state.get_state(session, conversation.id)
    assert estado.category is None
    assert estado.brand is None


async def test_gracias_solo_no_cierra(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact, conversation = await _preparar(
        session, "59170001405", horas=0.05, rubro="TV"
    )

    await Agent().handle(session, contact, "gracias!")

    estado = await conversation_state.get_state(session, conversation.id)
    assert estado.category == "TV"