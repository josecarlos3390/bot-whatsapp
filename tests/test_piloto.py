"""Informe del piloto: números y pendientes del día."""

from __future__ import annotations

from app.models import Contact, Conversation, Message
from scripts import pilot_report


def test_pendientes_empareja_pregunta_y_respuesta():
    class M:
        def __init__(self, direction, text):
            self.direction = direction
            self.text = text

    mensajes = [
        M("in", "busco un taladro"),
        M("out", "No encontré productos con ese criterio."),
        M("in", "gracias"),
        M("out", "De nada, que tengas buen día."),
    ]

    pendientes = pilot_report.pendientes_de(mensajes)

    assert pendientes["busco un taladro"] == 1
    assert len(pendientes) == 1


async def test_informe_cuenta_la_actividad(session):
    contacto = Contact(wa_id="59170019991", phone_e164="+59170019991")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    session.add_all(
        [
            Message(
                conversation_id=conversacion.id,
                direction="in",
                type="text",
                text="busco un taladro",
                wa_message_id="wamid-test-in-1",
            ),
            Message(
                conversation_id=conversacion.id,
                direction="out",
                type="text",
                text="No encontré productos con ese criterio.",
                wa_message_id="wamid-test-out-1",
            ),
        ]
    )
    await session.commit()

    texto, datos = await pilot_report.generar(24)

    assert datos["entrantes"] >= 1
    assert datos["salientes"] >= 1
    assert "Piloto" in texto



async def test_informe_sin_actividad(session):
    texto, datos = await pilot_report.generar(1)

    assert "Piloto" in texto
    assert isinstance(datos["conversaciones"], int)
