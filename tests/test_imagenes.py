"""Imágenes: interpretación y productos parecidos."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app.services import media as media_service
from app.services import vision


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_parseo_de_la_respuesta_de_vision():
    datos = vision._parsear(
        '```json\n{"objeto": "taladro percutor", "categoria": "taladros", '
        '"marca": "Bosch", "atributos": "13mm", "descripcion": "taladro azul"}\n```'
    )

    assert datos is not None
    assert datos["objeto"] == "taladro percutor"
    assert datos["marca"] == "Bosch"


def test_parseo_invalido_devuelve_none():
    assert vision._parsear("no pude ver la imagen") is None


async def test_sin_vision_pide_el_producto(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vision_api_key", "")
    monkeypatch.setattr(
        media_service,
        "download",
        _descarga_falsa,
    )
    contacto = Contact(wa_id="59170020001", phone_e164="+59170020001")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(
        session,
        contacto,
        "[image]",
        media={"kind": "image", "media_id": "abc"},
    )
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "imagen" in texto
    assert "qué producto" in texto or "que producto" in texto


async def test_con_vision_ofrece_parecidos(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vision_api_key", "clave")
    monkeypatch.setattr(settings, "vision_model", "modelo")
    monkeypatch.setattr(media_service, "download", _descarga_falsa)
    async def _describe_falso(contenido, mime):
        return _descripcion()

    monkeypatch.setattr(vision, "describe", _describe_falso)

    session.add(
        CatalogItem(
            sku="IMG-1",
            name="Taladro Percutor 13mm Bosch",
            price=900,
            stock=3,
            category="Taladros",
            brand="BOSCH",
            image_url="https://example.com/t.png",
            active=True,
        )
    )
    await session.commit()
    contacto = Contact(wa_id="59170020002", phone_e164="+59170020002")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(
        session,
        contacto,
        "[image]",
        media={"kind": "image", "media_id": "abc"},
    )
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "taladro" in texto
    assert "parecidas" in texto or "esto" in texto


async def _descarga_falsa(media_id):
    return b"contenido", "image/jpeg"


def _descripcion():
    return {
        "objeto": "taladro",
        "categoria": "taladros",
        "marca": "Bosch",
        "atributos": "13mm",
        "descripcion": "un taladro azul",
    }
