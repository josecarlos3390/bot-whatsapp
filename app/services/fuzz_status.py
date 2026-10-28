"""Estado del fuzzing para el panel: nota, tendencia y problemas."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORIAL = ROOT / "logs" / "fuzz-history.json"
REPORTE = ROOT / ".tools" / "fuzz-report.json"


def _leer(ruta: Path) -> list | dict | None:
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def status() -> dict:
    """Resumen para la tarjeta del panel."""
    historial = _leer(HISTORIAL) or []
    if not isinstance(historial, list):
        historial = []
    reporte = _leer(REPORTE) or []
    if not isinstance(reporte, list):
        reporte = []

    actual = historial[-1] if historial else {}
    anterior = historial[-2] if len(historial) >= 2 else None
    promedio = float(actual.get("promedio") or 0)
    previo = float(anterior.get("promedio") or 0) if anterior else None
    delta = round(promedio - previo, 2) if previo is not None else None

    problemas: list[str] = []
    for conversacion in reporte:
        for problema in (conversacion.get("problemas") or [])[:2]:
            if problema and problema not in problemas:
                problemas.append(str(problema)[:140])
    return {
        "promedio": promedio,
        "anterior": previo,
        "delta": delta,
        "corridas": len(historial),
        "criterios": actual.get("criterios") or {},
        "fecha": actual.get("fecha"),
        "problemas": problemas[:6],
        "escenarios": actual.get("escenarios", False),
    }
