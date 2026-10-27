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


def test_usa_la_clave_de_deepseek_si_no_hay_vision_dedicada(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vision_api_key", "")
    monkeypatch.setattr(settings, "vision_model", "")
    monkeypatch.setattr(settings, "deepseek_api_key", "clave-deepseek")

    credenciales = vision._credenciales()

    assert credenciales is not None
    assert credenciales[0] == "clave-deepseek"
    assert credenciales[2] == "deepseek-chat"


def test_ordena_por_marca_y_objeto():
    from app.agent import Agent

    productos = [
        {"name": "Pincel Silicona Verde", "category": "Accesorios de parrilla", "brand": "MOZC"},
        {"name": "Brocha 1plg Cerda Pet Ingco", "category": "Brochas", "brand": "INGCO"},
        {"name": "Brocha 2plg Cerda Pet Ingco", "category": "Brochas", "brand": "INGCO"},
    ]
    descripcion = {
        "objeto": "brocha de pintura",
        "categoria": "pinturería",
        "marca": "INGCO",
        "atributos": "1 pulgada",
    }

    ordenados = Agent._ordenar_por_imagen(productos, descripcion)

    assert ordenados[0]["brand"] == "INGCO"
    assert all("pincel" not in p["name"].lower() for p in ordenados[:2])

async def test_reconoce_el_mensaje_que_acompana_la_foto(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vision_api_key", "clave")
    monkeypatch.setattr(settings, "vision_model", "modelo")
    monkeypatch.setattr(media_service, "download", _descarga_falsa)

    async def _describe_falso(contenido, mime):
        return _descripcion()

    monkeypatch.setattr(vision, "describe", _describe_falso)
    session.add(
        CatalogItem(
            sku="IMG-2",
            name="Brocha 1plg Cerda Pet Ingco",
            price=9,
            stock=3,
            category="Brochas",
            brand="INGCO",
            image_url="https://example.com/b.png",
            active=True,
        )
    )
    await session.commit()
    contacto = Contact(wa_id="59170020003", phone_e164="+59170020003")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(
        session,
        contacto,
        "quiero comprar algo asi",
        media={"kind": "image", "media_id": "abc"},
    )
    texto = " ".join(m.text or "" for m in respuesta.messages).lower()

    assert "querés comprar algo así" in texto or "queres comprar algo asi" in texto
    assert "parecidas" in texto or "no encontré" in texto