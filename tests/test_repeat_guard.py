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


async def test_detecta_que_el_cliente_insiste(session):
    contacto, conversacion = await _contacto(session, "59170024004")
    session.add_all(
        [
            Message(
                conversation_id=conversacion.id,
                wa_message_id="wamid-ins-1",
                direction="in",
                type="text",
                text="¿Hacen envíos a Santa Cruz capital?",
            ),
            Message(
                conversation_id=conversacion.id,
                wa_message_id="wamid-ins-2",
                direction="in",
                type="text",
                text="¿Hacen envíos a Santa Cruz capital?",
            ),
        ]
    )
    await session.commit()

    assert (
        await repeat_guard.cliente_repite(
            session, contacto, "¿Hacen envíos a Santa Cruz capital?"
        )
        is True
    )


async def test_una_pregunta_nueva_no_es_insistencia(session):
    contacto, conversacion = await _contacto(session, "59170024005")
    session.add(
        Message(
            conversation_id=conversacion.id,
            wa_message_id="wamid-ins-3",
            direction="in",
            type="text",
            text="¿Hacen envíos a Santa Cruz capital?",
        )
    )
    await session.commit()

    assert (
        await repeat_guard.cliente_repite(
            session, contacto, "¿Cuánto sale un colchón de 2 plazas?"
        )
        is False
    )


def test_el_cambio_de_enfoque_ofrece_salida(session):
    texto = repeat_guard.cambio_de_enfoque(Contact(wa_id="1", name="Ana"))

    assert "Ana" in texto
    assert "asesor" in texto.lower()

async def test_con_asesor_asignado_no_ofrece_catalogo(session):
    from app.agent import Agent

    contacto, conversacion = await _contacto(session, "59170024006")
    conversacion.bot_paused = True
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "mostrame televisores")
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()
    botones = [
        boton["id"]
        for mensaje in respuesta.messages
        for boton in (mensaje.buttons or [])
    ]

    assert "asesor" in texto
    assert "catalog" not in botones