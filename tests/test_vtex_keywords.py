"""Keywords de VTEX y plurales: qué señal tenemos para clasificar."""

from __future__ import annotations

from app.services import catalog
from scripts import vtex_keywords_check


def test_gris_no_se_convierte_en_prefijo():
    assert catalog._base_variants("gris") == ["gris"]


def test_los_plurales_siguen_funcionando():
    variantes = catalog._base_variants("colchones")

    assert "colchones" in variantes
    assert "colchon" in variantes


def test_informe_avisa_que_no_hay_keywords():
    datos = {
        "items": 40,
        "campos": {"sku": 40, "name": 40, "specifications": 30},
        "tiene_keywords": False,
        "tiene_seo": False,
        "con_specs": 29,
        "spec_keys": [("Color", 24), ("Tamaño", 8)],
        "con_descripcion": 39,
        "con_nombre_completo": 0,
        "porcentaje_specs": 72.5,
        "porcentaje_descripcion": 97.5,
    }

    texto = vtex_keywords_check.informe(datos)

    assert "NO" in texto
    assert "especificaciones" in texto.lower()
    assert "Color" in texto
