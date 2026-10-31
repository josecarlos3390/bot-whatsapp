"""Botones de categoría: listas deterministas y sin texto repetido."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


async def _contacto(session, wa_id: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def test_categoria_devuelve_lista_de_productos(session):
    session.add_all(
        [
            CatalogItem(
                sku="SALA-SOFA",
                name="Sofá Bradford 2 Puestos Beige",
                price=5990,
                stock=3,
                category="MUEBLES",
                brand="BRADFORD",
                active=True,
            ),
            CatalogItem(
                sku="SALA-MESA",
                name="Mesa Central Asimétrica",
                price=1200,
                stock=2,
                category="MUEBLES",
                active=True,
            ),
            CatalogItem(
                sku="SALA-ESPEJO",
                name="Espejo Capela 60 Cozimax",
                price=399,
                stock=5,
                category="MUEBLES",
                brand="COZIMAX",
                active=True,
            ),
        ]
    )
    await session.commit()
    contacto = await _contacto(session, "59170021001")

    respuesta = await Agent().handle(session, contacto, "cat:sala")

    # Un solo mensaje: el menú con los productos y su precio.
    assert len(respuesta.messages) == 1
    mensaje = respuesta.messages[0]
    assert "Bs" in (mensaje.text or "")
    assert mensaje.kind == "list"
    titulos = [row["title"].lower() for row in mensaje.sections[0]["rows"]]
    # Primero lo del ambiente, no el espejo.
    assert "sof" in titulos[0] or "mesa" in titulos[0]
    assert "espejo" not in titulos[0]


async def test_categoria_no_repite_el_texto(session):
    session.add(
        CatalogItem(
            sku="SALA-SOFA-2",
            name="Sofá Acapulco 2p Cuero Avena",
            price=7990,
            stock=2,
            category="MUEBLES",
            active=True,
        )
    )
    await session.commit()
    contacto = await _contacto(session, "59170021002")

    respuesta = await Agent().handle(session, contacto, "cat:sala")

    textos = [
        (mensaje.text or "").strip().lower()
        for mensaje in respuesta.messages
        if mensaje.text
    ]
    assert len(textos) == len(set(textos))


def test_las_preguntas_por_rubro_llevan_a_busquedas_distintas():
    from app.services import categorias

    for clave, datos in categorias.PREGUNTAS.items():
        terminos = [termino for _, termino in datos["opciones"]]
        assert len(set(terminos)) == len(terminos), clave
        assert categorias.pregunta(clave) is not None


def test_una_categoria_sin_pregunta_no_pregunta():
    from app.services import categorias

    assert categorias.pregunta("ofertas") is None


def test_las_opciones_incluyen_ver_todo():
    from app.services import categorias

    filas = categorias.opciones("sala")
    assert filas[-1]["title"] == "Ver todo"
    assert filas[-1]["id"] == "sub:sala|todo"
    assert all(fila["id"].startswith("sub:") for fila in filas)