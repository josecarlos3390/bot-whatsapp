"""A/B del guard de repetición parcial.

Corre el fuzzing con el guard activado y desactivado, la misma cantidad de
veces, y compara las medianas. Sirve para decidir con datos si un cambio
aporta o solo agrega complejidad.

Uso:
    python -m scripts.fuzz_ab --corridas 3 --repeticiones 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORIAL = ROOT / "logs" / "fuzz-history.json"


def _leer_historial() -> list[dict]:
    if not HISTORIAL.exists():
        return []
    try:
        return json.loads(HISTORIAL.read_text(encoding="utf-8"))
    except ValueError:
        return []


def _mediana(valores: list[float]) -> float:
    return round(float(statistics.median(valores)), 2) if valores else 0.0


def correr(valor: str, corridas: int, repeticiones: int) -> list[float]:
    """Corre el fuzzing con el guard en `valor` y devuelve las notas."""
    import os

    from datetime import datetime, timezone

    marca = datetime.now(timezone.utc).isoformat()
    for _ in range(corridas):
        entorno = dict(os.environ)
        entorno["REPEAT_PARTIAL_ENABLED"] = valor
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.fuzz_conversations",
                "--escenarios",
                "--conversaciones",
                "6",
                "--turnos",
                "4",
                "--repeticiones",
                str(repeticiones),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=entorno,
        )
    # El historial se recorta a 24 entradas: se filtra por fecha, no por
    # posición.
    nuevos = [
        entrada
        for entrada in _leer_historial()
        if str(entrada.get("fecha") or "") >= marca
    ]
    return [
        float(entrada.get("promedio") or 0)
        for entrada in nuevos
        if isinstance(entrada.get("promedio"), (int, float))
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corridas", type=int, default=3)
    parser.add_argument("--repeticiones", type=int, default=3)
    args = parser.parse_args()

    print(f"A/B del guard parcial: {args.corridas} corridas por lado\n")
    sin_guard = correr("false", args.corridas, args.repeticiones)
    print(f"Sin guard: {sin_guard}")
    con_guard = correr("true", args.corridas, args.repeticiones)
    print(f"Con guard: {con_guard}")

    mediana_sin = _mediana(sin_guard)
    mediana_con = _mediana(con_guard)
    diferencia = round(mediana_con - mediana_sin, 2)
    print("\n--- resultado ---")
    print(f"Mediana sin guard: {mediana_sin}")
    print(f"Mediana con guard: {mediana_con}")
    print(f"Diferencia: {'+' if diferencia >= 0 else ''}{diferencia}")
    if diferencia > 0.15:
        print("Decisión: se queda el guard.")
    elif diferencia < -0.15:
        print("Decisión: se quita el guard.")
    else:
        print("Decisión: sin diferencia clara, se quita por simplicidad.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
