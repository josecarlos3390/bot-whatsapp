"""El fuzzing mide por criterios y compara corridas."""

from __future__ import annotations

from scripts import fuzz_scores


def test_promedio_de_notas():
    resultados = [{"nota": 4}, {"nota": 2}, {"nota": 3}]

    assert fuzz_scores.promedio(resultados) == 3.0


def test_promedio_sin_notas():
    assert fuzz_scores.promedio([{"nota": None}]) == 0.0


def test_promedio_por_criterio():
    resultados = [
        {"criterios": {"responde": 2, "no_inventa": 1}},
        {"criterios": {"responde": 0, "no_inventa": 1}},
    ]

    criterios = fuzz_scores.por_criterio(resultados)

    assert criterios["responde"] == 1.0
    assert criterios["no_inventa"] == 1.0


def test_comparacion_muestra_la_mejora():
    anterior = {"promedio": 2.0, "criterios": {"responde": 1.0}}
    actual = {"promedio": 3.5, "criterios": {"responde": 1.8}}

    lineas = fuzz_scores.comparar(anterior, actual)

    assert any("2.0 → 3.5" in linea for linea in lineas)
    assert any("responde" in linea for linea in lineas)


def test_sin_historial_es_linea_base():
    lineas = fuzz_scores.comparar(None, {"promedio": 2.0})

    assert "línea base" in lineas[0]
