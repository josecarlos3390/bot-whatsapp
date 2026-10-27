"""Ideas por intención: "algo para distraer a las visitas"."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation, ProductImage
from app.services import ideas


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_detecta_la_intencion_de_visitas():
    intent = ideas.detect("necesito algo para distraer a las visitas")

    assert intent is not None
    assert intent["clave"] == "visitas"


def test_no_confunde_una_busqueda_normal():
    assert ideas.detect("busco taladro percutor") is None


async def _catalogo(session):
    session.add_all(
        [
            CatalogItem(
                sku="IDEA-TV",
                name="TV 32 Smart LED Tokyo",
                price=1599,
                stock=4,
                category="TV",
                brand="TOKYO",
                image_url="https://example.com/tv.png",
                active=True,
            ),
            CatalogItem(
                sku="IDEA-VELA",
                name="Vela De Citronela Para Insectos Decore",
                price=24.9,
                stock=10,
                category="Macetas y accesorios",
                brand="DECORE",
                active=True,
            ),
            CatalogItem(
                sku="IDEA-MESA",
                name="Juego De Mesa Torre De Madera Fs",
                price=199,
                stock=6,
                category="Juegos de mesa",
                brand="FOSTER",
                image_url="https://example.com/juego.png",
                active=True,
            ),
        ]
    )
    await session.commit()


async def test_recomienda_tv_y_juego_no_la_vela(session):
    await _catalogo(session)
    contacto = Contact(wa_id="59170018881", phone_e164="+59170018881")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(
        session, contacto, "necesito algo para distraer a las visitas"
    )
    texto = " ".join(
        (m.text or "") for m in respuesta.messages
    ).lower()

    assert "televisor" in texto or "tv" in texto
    assert "citronela" not in texto
    assert "espanta" not in texto
    assert "vela" not in texto
