"""Control de calidad sobre conversaciones: detecta casos sospechosos."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Contact, Conversation, Message
from app.services import qa


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _conversation(session, wa_id: str) -> Conversation:
    contact = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.commit()
    return conversation


def _message(conversation, direction, text, *, minutes_ago=1, type_="text"):
    return Message(
        conversation_id=conversation.id,
        wa_message_id=f"wamid.{direction}.{minutes_ago}",
        direction=direction,
        type=type_,
        text=text,
        created_at=_now() - timedelta(minutes=minutes_ago),
    )


async def test_detecta_tema_delicitado_con_producto(session):
    conversation = await _conversation(session, "59170000901")
    session.add_all(
        [
            _message(conversation, "in", "Murió mi mascota", minutes_ago=2),
            _message(conversation, "out", "Sombrilla parasol. Precio: Bs 2.549", minutes_ago=1),
        ]
    )
    await session.commit()

    result = await qa.scan(session, hours=24)

    assert result["counts"].get("tema_delicitado") == 1


async def test_detecta_producto_sin_pedido(session):
    conversation = await _conversation(session, "59170000902")
    session.add_all(
        [
            _message(conversation, "in", "te cuento que me mudé", minutes_ago=2),
            _message(conversation, "out", "Decime cuál te interesa", minutes_ago=1),
        ]
    )
    await session.commit()

    result = await qa.scan(session, hours=24)

    assert result["counts"].get("producto_sin_pedido") == 1


async def test_consulta_de_producto_no_marca_anomalia(session):
    conversation = await _conversation(session, "59170000903")
    session.add_all(
        [
            _message(conversation, "in", "cuanto sale un colchon", minutes_ago=2),
            _message(conversation, "out", "Colchón Eco Flex. Precio: Bs 1.190", minutes_ago=1),
        ]
    )
    await session.commit()

    result = await qa.scan(session, hours=24)

    assert result["total"] == 0


async def test_detecta_mensaje_sin_respuesta(session):
    conversation = await _conversation(session, "59170000904")
    session.add(_message(conversation, "in", "hola?", minutes_ago=30))
    await session.commit()

    result = await qa.scan(session, hours=24)

    assert result["counts"].get("sin_respuesta") == 1
