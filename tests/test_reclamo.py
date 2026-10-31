"""Reclamos: el caso se toma completo antes de derivar."""

from __future__ import annotations

from app.agent import Agent
from app.models import Contact, Conversation
from app.services import reclamo


async def _contacto(session) -> tuple[Contact, Conversation]:
    contacto = Contact(
        wa_id="59170034001", phone_e164="+59170034001", name="Gabi"
    )
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.commit()
    return contacto, conversacion


async def test_un_reclamo_abre_el_caso(session):
    contacto, conversacion = await _contacto(session)

    respuesta = await reclamo.iniciar(
        session, contacto, "me llegó roto el producto"
    )

    assert "Lamento" in respuesta.messages[0].text
    assert reclamo.activo(conversacion)
    assert "roto" in (conversacion.summary or "")


async def test_el_caso_se_cierra_con_los_datos(session):
    contacto, conversacion = await _contacto(session)
    await reclamo.iniciar(session, contacto, "me llegó roto")

    await reclamo.continuar(session, contacto, "una licuadora")
    ultimo = await reclamo.continuar(session, contacto, "pedido 123")

    texto = ultimo.messages[0].text or ""
    assert "quedó registrado" in texto
    assert not reclamo.activo(conversacion)
    assert "licuadora" in (conversacion.summary or "")


async def test_el_bot_no_busca_productos_durante_el_caso(session):
    contacto, _ = await _contacto(session)
    await Agent().handle(session, contacto, "me llegó roto el producto")

    respuesta = await Agent().handle(session, contacto, "una licuadora")

    texto = (respuesta.messages[0].text or "").lower()
    assert "encontré" not in texto
    assert "opciones" not in texto


async def test_sin_reclamo_el_bot_atiende_normal(session):
    contacto, conversacion = await _contacto(session)

    assert not reclamo.activo(conversacion)
