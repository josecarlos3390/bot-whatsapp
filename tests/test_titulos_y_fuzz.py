"""Títulos cortos y alerta de calidad del fuzzing."""

from __future__ import annotations

from app.services import title_report
from scripts import nightly_fuzz


def test_recorta_sin_cortar_palabras():
    nombre = (
        "Taladro Percutor 13mm 20v 76nm 2bat Carg Acc Ingco "
        "TALADRO PERCUTOR 13MM INGCO"
    )
    corto = title_report.shorten(nombre)

    assert len(corto) <= 70
    assert corto.endswith("Ingco") or not corto.endswith(" ")
    assert "TALADRO PERCUTOR" not in corto


def test_titulo_corto_no_cambia():
    nombre = "Destornillador Plano 6mm Stanley"
    assert title_report.shorten(nombre) == nombre


def test_alerta_cuando_baja_la_calidad():
    decision = nightly_fuzz.evaluar(3.2, 2.1)
    assert decision["alerta"] is True
    assert decision["caida"] == 1.1


def test_sin_alerta_si_es_estable():
    decision = nightly_fuzz.evaluar(3.0, 2.6)
    assert decision["alerta"] is False


def test_sin_historial_no_alerta():
    assert nightly_fuzz.evaluar(None, 2.0)["alerta"] is False
