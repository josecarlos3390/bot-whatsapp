"""Limpieza de la descripción de VTEX (llega con HTML)."""

from scripts.sync_vtex import _plain


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
