"""Medidor de consumo de la IA: tokens y costo estimado."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import ai_usage


class _Uso:
    def __init__(self, prompt: int, completion: int, cache: int = 0) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = type(
            "D", (), {"cached_tokens": cache}
        )()


@pytest.fixture(autouse=True)
def _archivo_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_usage, "RUTA", tmp_path / "consumo-ia.jsonl")
    monkeypatch.setattr(settings, "deepseek_precio_entrada", 0.15)
    monkeypatch.setattr(settings, "deepseek_precio_entrada_cache", 0.003)
    monkeypatch.setattr(settings, "deepseek_precio_salida", 0.6)
    monkeypatch.setattr(settings, "deepseek_peak_multiplier", 2.0)


def test_extrae_los_tokens_del_uso():
    prompt, completion, cache = ai_usage._tokens(_Uso(1200, 300, 200))

    assert (prompt, completion, cache) == (1200, 300, 200)


def test_sin_uso_no_hay_tokens():
    assert ai_usage._tokens(None) == (0, 0, 0)


def test_calcula_el_costo_por_millon_offpeak():
    from datetime import datetime, timezone

    # Off-peak: 1M entrada 0,15 + 1M salida 0,60
    cuando = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    assert ai_usage.costo(1_000_000, 1_000_000, momento=cuando) == pytest.approx(
        0.75
    )


def test_el_cache_sale_mucho_mas_barato():
    from datetime import datetime, timezone

    cuando = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    con_cache = ai_usage.costo(1_000_000, 0, 1_000_000, cuando)
    sin_cache = ai_usage.costo(1_000_000, 0, 0, cuando)

    assert con_cache == pytest.approx(0.003)
    assert sin_cache == pytest.approx(0.15)


def test_en_horario_peak_paga_el_doble():
    from datetime import datetime, timezone

    peak = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    offpeak = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)

    assert ai_usage.costo(1_000_000, 0, 0, peak) == pytest.approx(0.30)
    assert ai_usage.costo(1_000_000, 0, 0, offpeak) == pytest.approx(0.15)


def test_la_ventana_offpeak_cruza_la_medianoche():
    from datetime import datetime, timezone

    assert ai_usage.es_offpeak(datetime(2026, 10, 30, 17, tzinfo=timezone.utc))
    assert ai_usage.es_offpeak(datetime(2026, 10, 30, 0, 10, tzinfo=timezone.utc))
    assert not ai_usage.es_offpeak(
        datetime(2026, 10, 30, 2, tzinfo=timezone.utc)
    )


def test_registra_una_llamada():
    fila = ai_usage.registrar("conversacion", _Uso(1000, 500))

    assert fila is not None
    assert fila["operacion"] == "conversacion"
    assert fila["prompt"] == 1000
    assert fila["costo_usd"] > 0


def test_una_operacion_desconocida_cae_en_otro():
    fila = ai_usage.registrar("inventada", _Uso(10, 5))

    assert fila["operacion"] == "otro"


def test_sin_tokens_no_registra():
    assert ai_usage.registrar("conversacion", None) is None


def test_resumen_agrupa_por_operacion():
    ai_usage.registrar("conversacion", _Uso(1000, 200))
    ai_usage.registrar("conversacion", _Uso(800, 100))
    ai_usage.registrar("imagen", _Uso(2000, 300))

    datos = ai_usage.resumen(dias=1)

    assert datos["llamadas"] == 3
    assert datos["prompt"] == 3800
    assert datos["operaciones"]["conversacion"]["llamadas"] == 2
    assert datos["operaciones"]["conversacion"]["prompt"] == 1800
    assert datos["costo_usd"] > 0
    assert len(datos["dias_detalle"]) == 1
