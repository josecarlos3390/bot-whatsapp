"""Saludo principal: formato, nombre y tres botones funcionales."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app import persona


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_el_saludo_tiene_el_formato_pedido():
    texto = persona.welcome("Chipi Cedeño")

    assert texto.startswith("¡Hola, Chipi! 👋")
    assert "ROHO Homecenter" in texto
    assert "asesora virtual" in texto
    assert "👇" in texto


def test_el_saludo_sin_nombre_no_deja_coma_suelta():
    texto = persona.welcome(None)

    assert texto.startswith("¡Hola! 👋")
    assert "Hola, " not in texto


def test_el_saludo_varia_la_pregunta():
    textos = {persona.welcome("Ana") for _ in range(30)}

    assert len(textos) > 1


async def test_el_saludo_muestra_tres_botones(session):
    contacto = Contact(wa_id="59170026001", phone_e164="+59170026001", name="Chipi")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "hola")
    mensaje = respuesta.messages[0]

    assert mensaje.kind == "buttons"
    titulos = [boton["title"] for boton in mensaje.buttons]
    assert titulos == [
        "Buscar productos",
        "Consultar mi pedido",
        "Hablar con un asesor",
    ]


async def test_buscar_productos_abre_las_categorias(session):
    contacto = Contact(wa_id="59170026002", phone_e164="+59170026002")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "catalog")

    assert respuesta.messages[0].kind == "list"
    assert "categoría" in (respuesta.messages[0].text or "").lower()


async def test_consultar_pedido_pide_el_id(session):
    contacto = Contact(wa_id="59170026003", phone_e164="+59170026003")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "estado")

    assert "ID del pedido" in (respuesta.messages[0].text or "")


async def test_el_boton_asesor_funciona_dentro_de_un_flujo(session):
    contacto = Contact(wa_id="59170026004", phone_e164="+59170026004")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    # Arranca el seguimiento y después pide un asesor.
    await Agent().handle(session, contacto, "estado")
    respuesta = await Agent().handle(session, contacto, "human")

    texto = (respuesta.messages[0].text or "").lower()
    assert "asesor" in texto or "equipo" in texto
    assert "id del pedido" not in texto


@pytest.mark.parametrize(
    "texto",
    ["Holaaaaaa", "holaa", "buenasaaa", "HOLAAAA", "hola que tal!!", "buenas tardes!!"],
)
async def test_los_saludos_estirados_tambien_saludan(session, texto):
    contacto = Contact(wa_id=f"5917{abs(hash(texto)) % 100000:05d}", phone_e164="+59170000000")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, texto)

    assert respuesta.messages[0].kind == "buttons"
    assert "ROHO Homecenter" in (respuesta.messages[0].text or "")


def test_el_colapso_quita_repeticiones():
    from app.agent import _sin_repeticiones

    assert _sin_repeticiones("Holaaaaaa") == "hola"
    assert _sin_repeticiones("HOLAAAA") == "hola"