"""Fuzzing nocturno: mide la calidad del bot y avisa si empeora.

Corre un puñado de conversaciones simuladas, guarda el promedio en un
historial y, si la nota baja respecto de la corrida anterior, deja un aviso
en logs/fuzz-alert.txt (y lo publica en el webhook si está configurado).
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
REPORTE = ROOT / ".tools" / "fuzz-report.json"
HISTORIAL = ROOT / "logs" / "fuzz-history.json"
AVISO = ROOT / "logs" / "fuzz-alert.txt"
UMBRAL = 0.7

logger = logging.getLogger("fuzz_nocturno")


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


def _historial() -> list[dict]:
    if not HISTORIAL.exists():
        return []
    try:
        return json.loads(HISTORIAL.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _guardar(entrada: dict) -> None:
    HISTORIAL.parent.mkdir(parents=True, exist_ok=True)
    datos = _historial()
    datos.append(entrada)
    HISTORIAL.write_text(
        json.dumps(datos[-90:], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _avisar(texto: str, webhook: str | None) -> None:
    AVISO.parent.mkdir(parents=True, exist_ok=True)
    AVISO.write_text(texto, encoding="utf-8")
    logger.warning(texto)
    if webhook:
        try:
            httpx.post(webhook, json={"event": "fuzz.alert", "detail": texto}, timeout=10)
        except Exception:  # noqa: BLE001 - el aviso no debe romper la corrida
            logger.exception("No se pudo publicar el aviso")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversaciones", type=int, default=6)
    parser.add_argument("--turnos", type=int, default=5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    comando = [
        sys.executable,
        "-m",
        "scripts.fuzz_conversations",
        "--conversaciones",
        str(args.conversaciones),
        "--turnos",
        str(args.turnos),
    ]
    resultado = subprocess.run(comando, cwd=ROOT, capture_output=True, text=True)
    if resultado.returncode != 0:
        logger.error("La corrida falló: %s", (resultado.stderr or "")[-500:])
        return 1
    if not REPORTE.exists():
        logger.error("No se generó el informe")
        return 1

    datos = json.loads(REPORTE.read_text(encoding="utf-8"))
    notas = [c.get("nota") for c in datos if isinstance(c.get("nota"), (int, float))]
    if not notas:
        logger.warning("Sin notas en el informe")
        return 0
    promedio = round(sum(notas) / len(notas), 2)

    historial = _historial()
    anterior = historial[-1].get("promedio") if historial else None
    decision = evaluar(anterior, promedio)

    entrada = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "promedio": promedio,
        "conversaciones": len(notas),
        "alerta": decision["alerta"],
    }
    _guardar(entrada)

    if decision["alerta"]:
        from app.config import settings

        _avisar(
            (
                f"Calidad del bot en baja: promedio {promedio} "
                f"(antes {anterior}). {decision['motivo']}.\n"
                f"Revisá el informe en .tools/fuzz-report.json"
            ),
            settings.handoff_webhook_url or None,
        )
    else:
        logger.info("Calidad estable: %s (antes %s)", promedio, anterior)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
