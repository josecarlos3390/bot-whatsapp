"""Orden de los mensajes: primero la lista, después la foto al elegir."""

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


def test_las_tarjetas_son_lista_y_menu_sin_fotos():
    tarjetas = Agent._search_cards([_producto(1), _producto(2), _producto(3)])

    tipos = [mensaje.kind for mensaje in tarjetas]
    assert tipos == ["text", "list"], tipos
    assert tarjetas[-1].kind == "list"
    assert tarjetas[-1].button_text == "Ver opciones"


def test_la_lista_dice_cuantas_opciones_y_el_precio():
    tarjetas = Agent._search_cards([_producto(1), _producto(2), _producto(3)])

    texto = tarjetas[0].text or ""
    assert "3 opciones" in texto
    assert "Bs 110" in texto
    assert "1. Espejo Modelo 1" in texto


def test_una_sola_opcion_no_dice_opciones():
    tarjetas = Agent._search_cards([_producto(1)])

    texto = tarjetas[0].text or ""
    assert "1 opciones" not in texto
    assert "1 opción" in texto


def test_muestra_hasta_cinco_opciones():
    productos = [_producto(numero) for numero in range(1, 9)]

    tarjetas = Agent._search_cards(productos)

    assert "5 opciones" in (tarjetas[0].text or "")
    assert len(tarjetas[-1].sections[0]["rows"]) == 5


def test_no_agrega_seguimos_despues_de_una_pregunta():
    from app.agent import Outbound

    salida = Agent._con_seguimiento(
        [Outbound(text="¿Alguna marca en particular o te muestro las más elegidas?")]
    )

    assert len(salida) == 1
    assert salida[0].kind == "text"


def test_no_agrega_seguimos_si_ya_hay_lista():
    from app.agent import Outbound

    salida = Agent._con_seguimiento(
        [
            Outbound(text="Encontré 1 opción:"),
            Outbound(kind="list", text="¿Cuál te interesa?", sections=[]),
        ]
    )

    assert len(salida) == 2


def test_si_la_respuesta_ya_lista_no_se_repiten_las_tarjetas():
    from app.agent import _ya_lista

    respuesta = (
        "En tecnología tenemos con descuento:\n"
        "- Cargador Pared 1USB Qualcomm — Bs 70 (antes Bs 199)\n"
        "- Cable Cargador Lightning — Bs 249"
    )
    productos = [
        {"sku": "A", "name": "Cargador Pared 1USB Qualcomm"},
        {"sku": "B", "name": "Cable Cargador Lightning"},
    ]

    assert _ya_lista(respuesta, productos) is True


def test_si_no_lista_no_se_omiten_las_tarjetas():
    from app.agent import _ya_lista

    assert (
        _ya_lista("¿Buscás algo para cargar el celular?", [
            {"sku": "A", "name": "Cargador Pared"}
        ])
        is False
    )
