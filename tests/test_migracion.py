"""Verificador de migración: arma el informe con estados."""

from __future__ import annotations

from scripts import check_migration


def test_resumen_marca_lo_que_falta():
    estado = {
        "numero": True,
        "cuenta": True,
        "webhook": False,
        "token": True,
        "telefono": "+59170000000",
        "cuenta": "+59170000000",
        "nombre": "ROHO Homecenter",
    }
    lineas = check_migration.resumen(estado)

    assert any("OK" in linea and "Número" in linea for linea in lineas)
    assert any("FALTA" in linea and "Webhook" in linea for linea in lineas)


def test_resumen_sin_configuracion():
    estado = {
        "numero": False,
        "cuenta": False,
        "webhook": False,
        "token": False,
    }
    lineas = check_migration.resumen(estado)

    assert all("FALTA" in linea for linea in lineas)
