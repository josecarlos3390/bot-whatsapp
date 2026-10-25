"""Regresiones detectadas revisando una conversación real."""

from __future__ import annotations

from app.agent import Agent, Toolbox
from app.models import CatalogItem, Contact, Conversation, FunnelEvent
from app.services import output_guard


def _producto(sku: str, nombre: str, precio: float, **extra) -> CatalogItem:
    datos = {
        "sku": sku,
        "name": nombre,
        "price": precio,
        "stock": 3,
        "active": True,
    }
    datos.update(extra)
    return CatalogItem(**datos)


async def test_busqueda_respeta_la_medida_pedida(session):
    """El modelo manda size aparte: hay que filtrar por esa medida."""
    from app.whatsapp import WhatsAppClient

    session.add_all(
        [
            _producto("TV-32", "Televisor Led 32 Pulgadas", 1599, category="TV"),
            _producto("TV-50", "Televisor Led 50 Pulgadas", 4699, category="TV"),
        ]
    )
    contact = Contact(wa_id="59170001201", phone_e164="+59170001201")
    session.add(contact)
    await session.commit()

    toolbox = Toolbox(session, contact, WhatsAppClient())
    resultado = await toolbox.tool_search_products(query="televisor", size="50")

    skus = [p["sku"] for p in resultado.get("products") or []]
    assert skus == ["TV-50"]


async def test_explica_por_que_recomendo_ese_producto(session):
    session.add(
        _producto("PANEL-1", "Panel De Tv Aegon 70", 1490, category="Muebles")
    )
    contact = Contact(wa_id="59170001202", phone_e164="+59170001202")
    session.add(contact)
    await session.flush()
    session.add(Conversation(contact_id=contact.id))
    session.add(
        FunnelEvent(
            step="product_view", contact_id=contact.id, sku="PANEL-1"
        )
    )
    await session.commit()

    reply = await Agent()._why_reply(session, contact)

    assert reply is not None
    texto = reply.messages[0].text or ""
    assert "Panel De Tv Aegon 70" in texto
    assert "precio" in texto.lower()
    assert "Bs 1,490.00" in texto


async def test_no_deja_oracion_cortada_al_reemplazar_frase(session):
    from app.agent import AgentReply, Outbound

    reply = AgentReply(
        [
            Outbound(
                text=(
                    "No tengo una sección específica de *vacaciones*, pero "
                    "esto es lo más cercano que tengo:"
                )
            )
        ]
    )

    result = await output_guard.sanitize(
        session, reply, "busco algo para vacaciones"
    )

    texto = result.messages[0].text or ""
    assert "sección específica" not in texto.lower()
    assert "lo más cercano" not in texto.lower()
    assert "esto es lo que tengo" in texto.lower()


async def test_respuesta_pendiente_no_encadena_oraciones(session, monkeypatch):
    """'No me gusta, mejor quiero tv' + 'De 50 pulgadas' no debe buscar la frase entera."""
    from app.config import settings
    from app.models import Conversation
    from app.services import conversation_guard

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170001210", phone_e164="+59170001210")
    session.add(contact)
    await session.flush()
    session.add(Conversation(contact_id=contact.id))
    await session.commit()

    # Simula la pregunta pendiente que dejó el mensaje anterior.
    await conversation_guard.set_pending(
        session,
        contact,
        slot="topic",
        question="¿Qué medida buscás?",
        query="No me gusta, mejor quiero tv",
    )

    reply = await Agent().handle(session, contact, "De 50 pulgadas, mejor si es oled")

    texto = " ".join(message.text or "" for message in reply.messages).lower()
    assert "no gusta" not in texto
    assert "mejor quiero" not in texto
    assert "no tengo nada" not in texto