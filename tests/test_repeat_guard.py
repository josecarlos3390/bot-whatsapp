"""No repetir la misma respuesta dos veces."""

from __future__ import annotations

from app.models import Contact, Conversation, Message
from app.services import repeat_guard


async def _contacto(session, wa_id: str) -> tuple[Contact, Conversation]:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.commit()
    return contacto, conversacion


async def test_detecta_la_respuesta_repetida(session):
    contacto, conversacion = await _contacto(session, "59170024001")
    texto = "Tenés razón en enojarte y te pido disculpas. Ya avisé al equipo."
    session.add(
        Message(
            conversation_id=conversacion.id,
            wa_message_id="wamid-rep-1",
            direction="out",
            type="text",
            text=texto,
        )
    )
    await session.commit()

    assert await repeat_guard.repetida(session, contacto, texto) is True


async def test_una_respuesta_distinta_no_es_repeticion(session):
    contacto, conversacion = await _contacto(session, "59170024002")
    session.add(
        Message(
            conversation_id=conversacion.id,
            wa_message_id="wamid-rep-2",
            direction="out",
            type="text",
            text="Ese producto no está disponible ahora mismo.",
        )
    )
    await session.commit()

    assert (
        await repeat_guard.repetida(
            session, contacto, "Tenemos tres opciones de taladro."
        )
        is False
    )


async def test_la_variante_nombra_al_cliente(session):
    contacto, _ = await _contacto(session, "59170024003")
    contacto.name = "Ana Pérez"
    await session.commit()

    texto = repeat_guard.variante(contacto)

    assert "Ana" in texto
    assert "asesor" in texto.lower()
