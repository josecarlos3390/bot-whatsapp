"""Orden de los mensajes: las fotos primero y el cierre al final."""

from __future__ import annotations

from app.agent import Agent


def _producto(numero: int) -> dict:
    return {
        "sku": f"ESP-{numero}",
        "name": f"Espejo Modelo {numero} 80x80",
        "price": str(100 + numero * 10),
        "stock": 3,
        "category": "Espejos",
        "brand": "COZIMAX",
        "image_url": f"https://example.com/espejo-{numero}.jpg",
    }


def test_las_fotos_van_antes_del_cierre():
    tarjetas = Agent._search_cards([_producto(1), _producto(2), _producto(3)])

    tipos = [mensaje.kind for mensaje in tarjetas]
    assert tipos == ["image", "image", "image", "list"], tipos
    assert tarjetas[-1].kind == "list"


def test_el_cierre_dice_cuantas_opciones():
    tarjetas = Agent._search_cards([_producto(1), _producto(2), _producto(3)])

    cierre = tarjetas[-1].text or ""
    assert "3 opciones" in cierre
    assert cierre.endswith(":")


def test_una_sola_opcion_no_dice_opciones():
    tarjetas = Agent._search_cards([_producto(1)])

    cierre = tarjetas[-1].text or ""
    assert "1 opciones" not in cierre
    assert "la opción" in cierre.lower()
