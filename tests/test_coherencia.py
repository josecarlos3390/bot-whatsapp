"""Coherencia: no mostrar otro rubro y entender atributos sueltos."""

from __future__ import annotations

import pytest

from app.agent import Agent, Toolbox
from app.models import CatalogItem, Contact, Conversation
from app.services import conversation_state


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


@pytest.fixture
async def catalogo(session):
    session.add_all(
        [
            CatalogItem(
                sku="TAL-1",
                name="Taladro Percutor 13mm Ingco",
                price=500,
                stock=5,
                category="Taladros",
                brand="INGCO",
                keywords="taladro percutor",
                image_url="https://example.com/t.jpg",
                active=True,
            ),
            CatalogItem(
                sku="ALF-1",
                name="Alfombra Mashru Marrón Lana",
                price=80,
                stock=5,
                category="Alfombras Decorativas",
                brand="HOME",
                keywords="alfombra",
                image_url="https://example.com/a.jpg",
                active=True,
            ),
        ]
    )
    await session.commit()
    return session


async def _contacto_con_rubro(session, wa_id: str, rubro: str) -> Contact:
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.commit()
    estado = await conversation_state.get_state(session, conversacion.id)
    estado.category = rubro
    await session.commit()
    return contacto


async def test_no_muestra_otro_rubro_por_un_modificador(catalogo):
    contacto = await _contacto_con_rubro(catalogo, "59170014441", "taladro")
    caja = Toolbox(catalogo, contacto, None)

    resultado = await caja.tool_search_products(query="precio mas bajo", limit=3)

    nombres = " ".join(p["name"] for p in resultado.get("products") or [])
    assert "Alfombra" not in nombres


async def test_permite_cambiar_de_rubro(catalogo):
    contacto = await _contacto_con_rubro(catalogo, "59170014442", "taladro")
    caja = Toolbox(catalogo, contacto, None)

    resultado = await caja.tool_search_products(query="ahora quiero alfombras", limit=3)

    nombres = " ".join(p["name"] for p in resultado.get("products") or [])
    assert "Alfombra" in nombres


async def test_atributo_suelto_se_completa_con_el_rubro(catalogo, monkeypatch):
    from app.config import settings
    from app.services import understanding

    monkeypatch.setattr(settings, "deepseek_api_key", "test")

    async def falso_parse(_client, _text):
        return {
            "intencion": "producto",
            "producto": None,
            "atributos": ["percutor"],
            "orden_precio": None,
            "referencia": "ultimo",
        }

    monkeypatch.setattr(understanding, "parse", falso_parse)

    contacto = await _contacto_con_rubro(catalogo, "59170014443", "taladro")
    respuesta = await Agent()._search_reply(catalogo, contacto, "de 13mm")

    textos = " ".join(m.text or "" for m in respuesta.messages)
    assert "Taladro Percutor" in textos
