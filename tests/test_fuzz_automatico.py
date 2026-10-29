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


def test_la_auditoria_evalua_por_prohibidas_y_esperadas():
    from scripts import auditoria_dialogos as auditoria

    ok, motivo = auditoria.evaluar(
        ["No tengo eso exacto, pero tengo opciones"], ["colchón"]
    )
    assert ok is False
    assert "no tengo" in motivo.lower()

    ok2, _ = auditoria.evaluar(["Tenemos colchones de 2 plazas"], ["colchón"])
    assert ok2 is True

    ok3, motivo3 = auditoria.evaluar(["Hola, ¿qué buscás?"], ["colchón"])
    assert ok3 is False


def test_los_casos_fijos_cubren_las_preguntas_del_bot():
    from scripts.auditoria_dialogos import CASOS

    identificadores = {caso["id"] for caso in CASOS}

    assert {"marca", "medida", "elegidas", "baratos", "asesor"} <= identificadores
    for caso in CASOS:
        assert caso["mensajes"] and caso["espera"]