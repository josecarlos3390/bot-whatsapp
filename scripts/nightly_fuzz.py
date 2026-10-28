"""Fuzzing automático: regresión diaria y exploración mensual.

Dos ritmos, los dos sin intervención:

- **Diario (regresión)**: corre los escenarios fijos y avisa si alguno
  empeora. Detecta que un cambio rompió algo que ya funcionaba.
- **Mensual (exploración)**: corre casos aleatorios para descubrir problemas
  nuevos que los escenarios fijos no cubren.

El historial y la comparación quedan en `logs/fuzz-history.json`.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
REPORTE = ROOT / ".tools" / "fuzz-report.json"
HISTORIAL = ROOT / "logs" / "fuzz-history.json"
AVISO = ROOT / "logs" / "fuzz-alert.txt"
UMBRAL = 0.7
UMBRAL_CRITERIO = 0.5

logger = logging.getLogger("fuzz_automatico")


def evaluar(anterior: float | None, actual: float, umbral: float = UMBRAL) -> dict:
    """Decide si la calidad bajó respecto de la corrida anterior."""
    if anterior is None:
        return {"alerta": False, "motivo": "sin historial previo", "caida": 0.0}
    caida = round(anterior - actual, 2)
    return {
        "alerta": caida >= umbral,
        "motivo": f"bajó {caida} puntos" if caida >= umbral else "estable",
        "caida": caida,
    }


def criterios_en_baja(anterior: dict, actual: dict) -> list[str]:
    """Criterios que empeoraron más de lo tolerable."""
    previos = anterior.get("criterios") or {}
    actuales = actual.get("criterios") or {}
    en_baja = []
    for clave, valor in actuales.items():
        previo = previos.get(clave)
        if previo is None:
            continue
        if float(previo) - float(valor) >= UMBRAL_CRITERIO:
            en_baja.append(f"{clave}: {previo} → {valor}")
    return en_baja


def _historial() -> list[dict]:
    if not HISTORIAL.exists():
        return []
    try:
        return json.loads(HISTORIAL.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _avisar(texto: str, webhook: str | None) -> None:
    AVISO.parent.mkdir(parents=True, exist_ok=True)
    AVISO.write_text(texto, encoding="utf-8")
    logger.warning(texto)
    if webhook:
        try:
            httpx.post(
                webhook, json={"event": "fuzz.alert", "detail": texto}, timeout=10
            )
        except Exception:  # noqa: BLE001 - el aviso no debe romper la corrida
            logger.exception("No se pudo publicar el aviso")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modo",
        choices=("regresion", "exploracion"),
        default="regresion",
        help=(
            "regresion: escenarios fijos (diario). "
            "exploracion: casos nuevos (mensual)."
        ),
    )
    parser.add_argument("--conversaciones", type=int, default=0)
    parser.add_argument("--turnos", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    exploracion = args.modo == "exploracion"
    conversaciones = args.conversaciones or (5 if exploracion else 6)
    turnos = args.turnos or (6 if exploracion else 4)

    comando = [
        sys.executable,
        "-m",
        "scripts.fuzz_conversations",
        "--conversaciones",
        str(conversaciones),
        "--turnos",
        str(turnos),
    ]
    if not exploracion:
        comando.append("--escenarios")

    logger.info("Corrida %s (%s conversaciones)", args.modo, conversaciones)
    resultado = subprocess.run(comando, cwd=ROOT, capture_output=True, text=True)
    if resultado.returncode != 0:
        logger.error("La corrida falló: %s", (resultado.stderr or "")[-500:])
        return 1
    if not REPORTE.exists():
        logger.error("No se generó el informe")
        return 1

    historial = _historial()
    actual = historial[-1] if historial else None
    # Solo se compara con una corrida del mismo tipo: 4 casos no se comparan
    # con 6.
    anterior = None
    if actual:
        for entrada in reversed(historial[:-1]):
            if (
                entrada.get("escenarios") == actual.get("escenarios")
                and entrada.get("casos") == actual.get("casos")
            ):
                anterior = entrada
                break
    if not actual:
        logger.warning("El fuzzing no dejó resumen en el historial")
        return 1

    decision = evaluar(
        float(anterior.get("promedio") or 0) if anterior else None,
        float(actual.get("promedio") or 0),
    )
    bajas = criterios_en_baja(anterior or {}, actual)

    if decision["alerta"] or bajas:
        from app.config import settings

        detalle = [f"Promedio: {actual.get('promedio')}"]
        if bajas:
            detalle.append("Criterios en baja: " + "; ".join(bajas))
        if decision["alerta"]:
            detalle.append(decision["motivo"])
        _avisar(
            (
                f"Fuzzing ({args.modo}): la calidad bajó.\n"
                + "\n".join(detalle)
                + "\nRevisá .tools/fuzz-report.json"
            ),
            settings.handoff_webhook_url or None,
        )
    else:
        logger.info(
            "Calidad estable: %s (antes %s)",
            actual.get("promedio"),
            anterior.get("promedio") if anterior else None,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
