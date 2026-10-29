"""Detección de contactos de prueba (artefactos de simulación)."""

from __future__ import annotations

from scripts import limpiar_contactos_prueba as limpieza


def test_un_telefono_valido_no_es_prueba():
    assert limpieza.es_prueba("59169006969", "+59169006969") is False


def test_wa_id_con_letras_es_prueba():
    assert limpieza.es_prueba("5917fed89f005", "+5917fed89f005") is True


def test_telefono_truncado_es_prueba():
    assert limpieza.es_prueba("5917149", "+5917149") is True


def test_sin_telefono_es_prueba():
    assert limpieza.es_prueba("59169006969", None) is True
