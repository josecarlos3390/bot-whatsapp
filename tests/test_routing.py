"""Matriz de enrutamiento: cada mensaje debe entrar por la capa correcta.

Se verifica la traza de decisión, no el texto. Es lo que evita que un arreglo
en una capa rompa la prioridad de otra.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


@pytest.fixture
async def catalogo(session):
    session.add_all(
        [
            CatalogItem(
                sku="TV-50",
                name="Televisor Led 50 Pulgadas Samsung",
                price=4699,
                stock=3,
                category="TV",
                brand="SAMSUNG",
                keywords="tv televisor",
                active=True,
            ),
            CatalogItem(
                sku="COLCH-2",
                name="Colchón Eco Flex 2 Plazas",
                price=1190,
                stock=6,
                category="Colchones",
                brand="FLEX",
                keywords="colchon",
                active=True,
            ),
        ]
    )
    await session.commit()
    return session


async def _contacto(session, wa_id: str, horas: float = 0) -> Contact:
    contact = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contact)
    await session.flush()
    conversation = Conversation(contact_id=contact.id)
    if horas:
        conversation.last_message_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=horas)
        )
    session.add(conversation)
    await session.commit()
    return contact


# (mensaje, fragmento esperado en la traza)
MATRIZ = [
    ("Quien eres?", "Identidad"),
    ("quién sos?", "Identidad"),
    ("que podes hacer?", "Identidad"),
    ("estoy triste", "Empatía"),
    ("murió mi mascota", "Empatía"),
    ("esto es una estafa, nadie me atiende", "Enojo"),
    ("hace una hora esperando respuesta", "Enojo"),
    ("¿qué remedio tomo para el dolor?", "política"),
    ("quiero demandar a la tienda", "política"),
    ("pasame el número de tarjeta", "política"),
    ("gracias, hasta luego", "despedida"),
    # Ahora se cotiza el envío por ciudad en vez de copiar el artículo.
    ("hacen envíos a Santa Cruz?", "Envío"),
    ("cuanto tarda la entrega?", "Política publicada"),
    ("busco colchón de 2 plazas", "Búsqueda"),
    ("cuanto sale un televisor de 50 pulgadas", "Búsqueda"),
    ("me voy de viaje la semana que viene", "Personal"),
    ("venden algo para halloween?", "Ocasión"),
]


@pytest.mark.parametrize("mensaje,capa", MATRIZ, ids=[caso[0] for caso in MATRIZ])
async def test_enrutamiento(catalogo, mensaje, capa):
    contact = await _contacto(
        catalogo, f"5917001{abs(hash(mensaje)) % 100000:05d}"
    )
    agente = Agent()

    await agente.handle(catalogo, contact, mensaje)

    traza = " | ".join(agente.trace)
    assert capa.lower() in traza.lower(), f"{mensaje!r} fue por {traza or 'ninguna capa'}"


async def test_charla_nueva_tras_pausa(catalogo):
    contact = await _contacto(catalogo, "59170019001", horas=8)
    agente = Agent()

    await agente.handle(catalogo, contact, "busco colchones")

    assert any("Charla nueva" in nota for nota in agente.trace)


async def test_cambio_de_rubro_no_arrastra_marca(catalogo):
    from sqlalchemy import select

    from app.models import Conversation
    from app.services import conversation_state

    contact = await _contacto(catalogo, "59170019002")
    conv = await catalogo.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    # Estado previo: venía mirando televisores.
    estado = await conversation_state.get_state(catalogo, conv.id)
    estado.category = "TV"
    estado.brand = "SAMSUNG"
    await catalogo.commit()

    agente = Agent()
    await agente.handle(catalogo, contact, "busco colchón de 2 plazas")

    assert any("Cambio de rubro" in nota for nota in agente.trace)
