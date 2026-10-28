"""Fuzzing automático: diario de regresión y mensual de exploración."""

from __future__ import annotations

from scripts import nightly_fuzz


def test_detecta_caida_del_promedio():
    decision = nightly_fuzz.evaluar(3.0, 2.0)

    assert decision["alerta"] is True
    assert decision["caida"] == 1.0


def test_sin_caida_no_alerta():
    assert nightly_fuzz.evaluar(3.0, 2.6)["alerta"] is False


def test_detecta_criterios_en_baja():
    anterior = {"criterios": {"responde": 1.8, "tono": 1.9}}
    actual = {"criterios": {"responde": 0.9, "tono": 1.8}}

    bajas = nightly_fuzz.criterios_en_baja(anterior, actual)

    assert len(bajas) == 1
    assert "responde" in bajas[0]


def test_cambios_pequenos_no_alarman():
    anterior = {"criterios": {"responde": 1.5}}
    actual = {"criterios": {"responde": 1.2}}

    assert nightly_fuzz.criterios_en_baja(anterior, actual) == []


def test_los_escenarios_fijos_existen():
    from scripts.fuzz_conversations import ESCENARIOS

    identificadores = {caso["id"] for caso in ESCENARIOS}

    assert {"pedido-id", "stock", "envio-zona", "enojo", "precio", "imagen"} <= identificadores
