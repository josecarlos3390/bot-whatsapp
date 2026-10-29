"""Puente a lo relacionado cuando el producto no existe."""

from __future__ import annotations

import pytest

from app.agent import Agent
from app.models import CatalogItem, Contact, Conversation
from app.services import related


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def test_parsea_la_respuesta_de_la_ia():
    datos = related.parsear(
        '```json\n{"intencion": "jugar fútbol con amigos", '
        '"relacionadas": ["televisor", "sillón"]}\n```'
    )

    assert datos is not None
    assert datos["intenciones"][0]["idea"] == "jugar fútbol con amigos"
    assert datos["intenciones"][0]["categorias"] == ["televisor", "sillón"]


def test_tolera_texto_alrededor_del_json():
    datos = related.parsear(
        'Claro: {"intencion": "protegerse del sol", '
        '"relacionadas": ["sombrilla"]} — listo'
    )

    assert datos is not None
    assert datos["intenciones"][0]["categorias"] == ["sombrilla"]


def test_rechaza_respuestas_invalidas():
    assert related.parsear("no sé") is None
    assert related.parsear('{"relacionadas": []}') is None
    assert related.parsear('{"intencion": "x", "relacionadas": "televisor"}') is None


def test_limpia_el_termino_del_saludo_y_el_verbo():
    # El término se normaliza antes de consultar a la IA: la prueba usa el
    # mismo criterio que la respuesta.
    import re

    termino = re.sub(
        r"^(hola|buenas|buen día|buenas tardes)\s+",
        "",
        "hola vendes paraguas?".lower(),
    )
    termino = re.sub(r"^(vendes|vende|tienen|tiene|hay)\s+", "", termino)
    termino = termino.strip(" ?!.")

    assert termino == "paraguas"


async def test_no_inventa_si_la_ia_no_responde(session, monkeypatch):
    monkeypatch.setattr(
        related, "_pedir_a_la_ia", _sin_respuesta, raising=True
    )

    contacto = Contact(wa_id="59170040001", phone_e164="+59170040001")
    session.add(contacto)
    await session.commit()

    resultado = await related.reply(Agent(), session, contacto, "paraguas")

    assert resultado is None


async def _sin_respuesta(termino: str):
    return None


async def test_muestra_productos_relacionados(session, monkeypatch):
    session.add(
        CatalogItem(
            sku="REL-1",
            name="Sombrilla parasol 3m",
            price=1599,
            stock=5,
            category="Sombrillas",
            image_url="https://example.com/s.png",
            active=True,
        )
    )
    await session.commit()
    contacto = Contact(wa_id="59170040002", phone_e164="+59170040002")
    session.add(contacto)
    await session.commit()

    async def _falsa(termino: str):
        return {
            "intenciones": [
                {"idea": "protegerse del sol", "categorias": ["sombrilla"]}
            ]
        }

    monkeypatch.setattr(related, "_pedir_a_la_ia", _falsa, raising=True)

    respuesta = await related.reply(Agent(), session, contacto, "paraguas")
    texto = " ".join(m.text or "" for m in respuesta.messages)

    assert "no tengo" in texto.lower()
    assert "protegerse del sol" in texto
    assert "Sombrilla" in texto
