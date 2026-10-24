"""Latencia de respuesta: se mide cada turno y se resume para el tablero.

Se guarda en un archivo JSONL (sin migraciones) y se recorta solo.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PATH = Path(".tools") / "latency.jsonl"
MAX_LINES = 4000
SLOW_MS = 8000


def record(ms: float) -> None:
    """Anota una respuesta (milisegundos)."""
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ms": int(ms),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                + "\n"
            )
            if ms >= SLOW_MS:
                logger.warning("Respuesta lenta: %.0f ms", ms)
    except Exception:  # noqa: BLE001 - la métrica nunca frena la charla
        logger.debug("No se pudo registrar la latencia", exc_info=True)


def _load() -> list[int]:
    if not PATH.exists():
        return []
    values: list[int] = []
    try:
        with PATH.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    values.append(int(json.loads(line)["ms"]))
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return []
    return values


def _trim(values: list[int]) -> None:
    if len(values) <= MAX_LINES:
        return
    try:
        kept = values[-MAX_LINES:]
        PATH.write_text(
            "".join(json.dumps({"ms": value}) + "\n" for value in kept),
            encoding="utf-8",
        )
    except OSError:
        logger.debug("No se pudo recortar el archivo de latencias", exc_info=True)


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summary(window: int = 500) -> dict:
    values = _load()
    if not values:
        return {
            "count": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "max_ms": 0,
            "slow": 0,
            "slow_limit_ms": SLOW_MS,
        }
    _trim(values)
    recent = values[-window:]
    return {
        "count": len(recent),
        "p50_ms": percentile(recent, 0.5),
        "p95_ms": percentile(recent, 0.95),
        "max_ms": max(recent),
        "slow": sum(1 for value in recent if value >= SLOW_MS),
        "slow_limit_ms": SLOW_MS,
    }
