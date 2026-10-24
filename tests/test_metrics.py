"""Latencia: percentiles y registro."""

from __future__ import annotations

import json

from app.services import metrics


def test_percentiles_basicos():
    valores = [100, 200, 300, 400, 500]
    assert metrics.percentile(valores, 0.5) == 300
    assert metrics.percentile(valores, 0.95) == 500
    assert metrics.percentile([], 0.5) == 0


def test_resumen_lee_el_archivo(tmp_path, monkeypatch):
    archivo = tmp_path / "latency.jsonl"
    archivo.write_text(
        "".join(json.dumps({"ms": value}) + "\n" for value in [1000, 2000, 9000]),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "PATH", archivo)

    resumen = metrics.summary(10)

    assert resumen["count"] == 3
    assert resumen["p95_ms"] == 9000
    assert resumen["max_ms"] == 9000
    assert resumen["slow"] == 1


def test_registrar_no_falla_sin_directorio(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "PATH", tmp_path / "sub" / "latency.jsonl")

    metrics.record(1234)

    assert metrics.PATH.exists()
