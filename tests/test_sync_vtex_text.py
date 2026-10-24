"""Limpieza de la descripción de VTEX (llega con HTML)."""

from scripts.sync_vtex import _display_name, _plain


def test_quita_etiquetas_y_entidades():
    html = (
        "<p>La brocha de 1 1/2 pulg. est&aacute; pensada para "
        "<strong>pintura</strong>.</p><p>Caracter&iacute;sticas:</p>"
    )

    text = _plain(html)

    assert "<" not in text
    assert "está pensada" in text
    assert "pintura" in text


def test_colapsa_espacios_y_limita():
    assert _plain("<p>a</p>\n\n<p>b</p>") == "a b"
    assert len(_plain("<p>" + "x" * 50 + "</p>", 10)) == 10


def test_vacio_devuelve_none():
    assert _plain(None) is None
    assert _plain("<p> </p>") is None


def test_nombre_sin_duplicar_sku():
    # VTEX repite el nombre del SKU en mayúsculas al final.
    row = {
        "product_name": "Colchón Eco Flex 2 Plazas 140X190cm Flex",
        "name_complete": (
            "Colchón Eco Flex 2 Plazas 140X190cm Flex "
            "COLCHON ECO FLEX 2 PLAZAS 140X190CM FLEX"
        ),
    }
    assert _display_name(row) == "Colchón Eco Flex 2 Plazas 140X190cm Flex"


def test_nombre_conserva_sku_si_aporta():
    row = {
        "product_name": "Colchón Euro Pedic",
        "name_complete": "Colchón Euro Pedic 2 Plazas 160x190",
    }
    assert _display_name(row) == "Colchón Euro Pedic 2 Plazas 160x190"