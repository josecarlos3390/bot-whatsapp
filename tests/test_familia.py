"""Productos afines cuando no hay lo que el cliente pide."""

from __future__ import annotations

from app.services import familia


def test_monitor_sugiere_televisores():
    terminos = familia.terminos("monitor")

    assert "televisor" in terminos
    assert "monitor" not in terminos


def test_impresora_no_sugiere_pintura():
    # "Tinta" en este catálogo es pintura, no insumo de impresora.
    assert familia.terminos("impresora") == ()


def test_un_objeto_desconocido_no_inventa():
    assert familia.terminos("telescopio") == ()


def test_la_categoria_generica_no_sirve_para_sugerir():
    from app.flows.media import _categoria_util

    assert not _categoria_util("electrónica")
    assert not _categoria_util("Electronica")
    assert not _categoria_util("otros")
    assert _categoria_util("Monitores")
    assert _categoria_util("Soportes para TV")


def test_una_ducha_no_coincide_con_un_monitor():
    from app.flows.media import _coincide

    descripcion = {
        "objeto": "monitor",
        "categoria": "electrónica",
        "marca": "Samsung",
        "atributos": "pantalla plana 24 pulgadas",
    }
    ducha = {"name": "Gran Ducha Electrónica 7000W Blanca", "category": "Duchas"}

    assert not _coincide(descripcion, ducha)
