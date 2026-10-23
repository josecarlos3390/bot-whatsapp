"""Especificaciones de VTEX en el catálogo y en la ficha."""

from __future__ import annotations

from decimal import Decimal

from app.agent import Agent
from app.models import CatalogItem, Contact
from scripts.sync_vtex import _specs


def test_limpia_especificaciones():
    specs = _specs(
        {
            "specifications": {
                "Garantía": "5 Años",
                "Medidas": "<b>105 x 190 x 24 cm</b>",
                "Color": "",
                "  ": "vacío",
            }
        }
    )

    assert specs["Garantía"] == "5 Años"
    assert specs["Medidas"] == "105 x 190 x 24 cm"
    assert "Color" not in specs
    assert len(specs) == 2


def test_sin_especificaciones():
    assert _specs({}) == {}
    assert _specs({"specifications": None}) == {}
    assert _specs({"specifications": "texto"}) == {}


async def test_la_ficha_muestra_garantia_y_medidas(session):
    session.add(
        CatalogItem(
            sku="COLCH-SPEC",
            name="COLCHON SEMIPEDIC 2 PLAZAS",
            price=Decimal("2240"),
            stock=5,
            brand="HEAVEN",
            active=True,
            attributes={
                "source": "vtex",
                "specs": {
                    "Garantía": "5 Años",
                    "Medidas": "105 x 190 x 24 cm",
                    "Nivel de soporte": "Firme",
                },
            },
        )
    )
    contact = Contact(wa_id="59170000991", phone_e164="+59170000991")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "product:COLCH-SPEC")

    text = " ".join(message.text or "" for message in reply.messages)
    assert "Garantía: 5 Años" in text
    assert "Medidas: 105 x 190 x 24 cm" in text
