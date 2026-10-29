"""Verificación del cambio del PaaS (documento sí, secuencia no)."""

from __future__ import annotations

from scripts import verificar_secuencia as verificar


def test_todo_bien_cuando_el_cambio_esta_aplicado():
    ok, lineas = verificar.evaluar(
        documento=[{"orderId": "1"}],
        secuencia_por_cliente=[],
        secuencia_explicita={"orderId": "1672200500195-01"},
    )

    assert ok is True
    assert any("documento devuelve" in linea for linea in lineas)


def test_falla_si_la_secuencia_sigue_resolviendo_por_cliente():
    ok, lineas = verificar.evaluar(
        documento=[{"orderId": "1"}],
        secuencia_por_cliente=[{"orderId": "ajeno"}],
        secuencia_explicita={"orderId": "1"},
    )

    assert ok is False
    assert any("todavía devuelve pedidos" in linea for linea in lineas)


def test_falla_si_no_existe_la_ruta_de_secuencia():
    ok, lineas = verificar.evaluar(
        documento=[{"orderId": "1"}],
        secuencia_por_cliente=[],
        secuencia_explicita=None,
    )

    assert ok is False
    assert any("by-sequence" in linea for linea in lineas)


def test_falla_si_el_documento_no_devuelve_nada():
    ok, lineas = verificar.evaluar(
        documento=[],
        secuencia_por_cliente=[],
        secuencia_explicita={"orderId": "1"},
    )

    assert ok is False
    assert any("documento no devuelve" in linea for linea in lineas)
