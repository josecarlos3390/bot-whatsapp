"""Cotización de envío por ciudad, desde las tarifas del negocio."""

from __future__ import annotations

import json

from app.services import envio


def test_lee_las_zonas():
    zonas = envio.zonas()

    assert len(zonas) >= 4
    assert envio.por_clave("la-paz")["costo"] == 45


def test_encuentra_la_zona_por_alias():
    assert envio.buscar("mándalo a Montero")["clave"] == "santa-cruz-provincias"
    assert envio.buscar("para Cochabamba")["clave"] == "cochabamba"
    assert envio.buscar("a Oruro")["clave"] == "resto"
    assert envio.buscar("no sé") is None


def test_cotiza_con_costo_y_plazo():
    texto = envio.cotizar(envio.por_clave("la-paz"))

    assert "Bs 45" in texto
    assert "48 horas" in texto


def test_el_retiro_es_sin_costo():
    assert "sin costo" in envio.retiro().lower()


def test_las_opciones_llevan_la_zona():
    filas = envio.opciones()

    assert len(filas) >= 4
    assert all(fila["id"].startswith("envio:") for fila in filas)
    assert any("resto" in fila["id"] for fila in filas)


def test_las_tarifas_son_json_valido():
    from pathlib import Path

    datos = json.loads(
        Path("knowledge/tarifas-envio.json").read_text(encoding="utf-8")
    )
    for zona in datos["zonas"]:
        assert zona["clave"] and zona["etiqueta"]
        assert zona["costo"] > 0
