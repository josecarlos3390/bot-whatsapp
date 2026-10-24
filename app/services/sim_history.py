"""Historial de pruebas del bot desde la consola.

Se guarda en un JSONL y se recorta solo: sirve para comparar una respuesta
antes y después de un cambio.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PATH = Path(".tools") / "console_simulations.jsonl"
MAX_LINES = 300


def record(
    *,
    text: str,
    ms: int,
    trace: list[str] | None = None,
    preview: str = "",
    error: str | None = None,
) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "text": (text or "")[:300],
                        "ms": int(ms or 0),
                        "trace": trace or [],
                        "preview": (preview or "")[:220],
                        "error": error,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        _trim()
    except Exception:  # noqa: BLE001 - la prueba no falla por el historial
        logger.debug("No se pudo guardar la prueba", exc_info=True)


def _trim() -> None:
    if not PATH.exists():
        return
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LINES:
            PATH.write_text(
                "\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8"
            )
    except OSError:
        logger.debug("No se pudo recortar el historial", exc_info=True)


def recent(limit: int = 15) -> list[dict]:
    if not PATH.exists():
        return []
    items: list[dict] = []
    try:
        for line in PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return list(reversed(items[-max(int(limit), 1) :]))
