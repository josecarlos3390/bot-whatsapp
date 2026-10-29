"""Salud del envío: detecta cuando el bot deja de poder responder.

Si los envíos fallan seguido (token vencido, número bloqueado, límite de
mensajería), el bot sigue guardando los mensajes entrantes pero el cliente no
recibe nada. Esto lo cuenta y avisa.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AVISO = Path("logs") / "envios-alerta.txt"
UMBRAL_AVISO = 3

_fallos_seguidos = 0
_fallos_total = 0
_ultimo_error = ""
_ultimo_ok = None


def record_success() -> None:
    global _fallos_seguidos, _ultimo_ok
    _fallos_seguidos = 0
    _ultimo_ok = datetime.now(timezone.utc)


def record_failure(error: str) -> None:
    global _fallos_seguidos, _fallos_total, _ultimo_error
    _fallos_seguidos += 1
    _fallos_total += 1
    _ultimo_error = str(error)[:300]
    logger.warning(
        "Envío fallido (%s seguidos): %s", _fallos_seguidos, _ultimo_error
    )
    if _fallos_seguidos >= UMBRAL_AVISO:
        _avisar()


def _avisar() -> None:
    """Deja un aviso visible cuando el envío lleva varios fallos."""
    try:
        AVISO.parent.mkdir(parents=True, exist_ok=True)
        AVISO.write_text(
            (
                f"{datetime.now(timezone.utc).isoformat()}\n"
                f"El bot lleva {_fallos_seguidos} envíos fallidos seguidos.\n"
                f"Último error: {_ultimo_error}\n"
                "Los clientes están escribiendo pero no reciben respuesta.\n"
                "Revisar WA_ACCESS_TOKEN, el número y el límite de mensajería.\n"
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("No se pudo escribir el aviso de envíos")


def status() -> dict:
    return {
        "fallos_seguidos": _fallos_seguidos,
        "fallos_total": _fallos_total,
        "ultimo_error": _ultimo_error,
        "ultimo_ok": _ultimo_ok.isoformat() if _ultimo_ok else None,
        "alerta": _fallos_seguidos >= UMBRAL_AVISO,
    }


def reset() -> None:
    """Solo para pruebas."""
    global _fallos_seguidos, _fallos_total, _ultimo_error, _ultimo_ok
    _fallos_seguidos = 0
    _fallos_total = 0
    _ultimo_error = ""
    _ultimo_ok = None
