"""Transcripción de notas de voz.

DeepSeek no transcribe audio: sus modelos son de texto. Para las notas de voz
se usa Whisper en local (faster-whisper), sin costo por minuto y sin mandar el
audio a terceros. El audio de WhatsApp es OGG/Opus: se decodifica con el
ffmpeg que trae imageio-ffmpeg y se convierte a 16 kHz mono.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

_modelo = None
_cargando: asyncio.Lock | None = None
# Si OpenAI falla seguido (red bloqueada), no se reintenta por un rato.
_fallos_openai = 0
_openai_hasta = 0.0

MODELOS = Path(".models")


def _preparar_av() -> None:
    """faster-whisper importa PyAV, que falla en este Windows.

    Solo se usa para decodificar; acá decodificamos con ffmpeg, así que se
    deja un módulo vacío para que el import no rompa.
    """
    if "av" not in sys.modules:
        sys.modules["av"] = types.ModuleType("av")


def disponible() -> bool:
    """¿Están las dependencias para transcribir?"""
    try:
        _preparar_av()
        import faster_whisper  # noqa: F401
        import imageio_ffmpeg  # noqa: F401
        import numpy  # noqa: F401
    except Exception:  # noqa: BLE001 - si falta algo, no hay voz
        return False
    return True


def _cargar_modelo():
    global _modelo
    if _modelo is not None:
        return _modelo
    _preparar_av()
    from faster_whisper import WhisperModel

    MODELOS.mkdir(exist_ok=True)
    logger.info("Cargando modelo de voz %s", settings.transcribe_model)
    _modelo = WhisperModel(
        settings.transcribe_model,
        device=settings.transcribe_device,
        compute_type=settings.transcribe_compute,
        download_root=str(MODELOS),
    )
    return _modelo


def _decodificar(audio: bytes, mime: str) -> bytes:
    """Convierte el audio a PCM 16 kHz mono con el ffmpeg incluido."""
    import imageio_ffmpeg

    sufijo = ".ogg"
    if "mp4" in (mime or "") or "m4a" in (mime or ""):
        sufijo = ".m4a"
    elif "mpeg" in (mime or ""):
        sufijo = ".mp3"
    elif "wav" in (mime or ""):
        sufijo = ".wav"
    with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as archivo:
        archivo.write(audio)
        ruta = archivo.name
    try:
        salida = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-v",
                "quiet",
                "-i",
                ruta,
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-",
            ],
            capture_output=True,
            timeout=60,
        )
        return salida.stdout
    finally:
        Path(ruta).unlink(missing_ok=True)


def transcribir_sync(audio: bytes, mime: str = "audio/ogg") -> str:
    """Transcribe de forma bloqueante (se llama desde un hilo)."""
    import numpy as np

    crudo = _decodificar(audio, mime)
    if len(crudo) < 3200:  # menos de 0,1 s: no hay voz
        return ""
    muestras = np.frombuffer(crudo, dtype=np.int16).astype(np.float32)
    muestras /= 32768.0
    modelo = _cargar_modelo()
    segmentos, _ = modelo.transcribe(
        muestras,
        language=settings.transcribe_language,
        vad_filter=True,
        beam_size=1,
    )
    return " ".join(segmento.text.strip() for segmento in segmentos).strip()


def motor() -> str:
    """Qué motor se va a usar: openai, local o ninguno."""
    if not settings.transcribe_enabled:
        return "ninguno"
    preferido = (settings.transcribe_backend or "auto").lower()
    hay_openai = bool(settings.openai_api_key)
    if preferido == "openai":
        return "openai" if hay_openai else "ninguno"
    if preferido == "local":
        return "local" if disponible() else "ninguno"
    if hay_openai:
        return "openai"
    return "local" if disponible() else "ninguno"


async def transcribir(audio: bytes, mime: str = "audio/ogg") -> str:
    """Transcribe con el motor configurado; vacío si no se pudo."""
    global _cargando, _fallos_openai, _openai_hasta
    elegido = motor()
    if elegido == "ninguno":
        return ""
    if elegido == "openai" and time.time() < _openai_hasta:
        elegido = "local" if disponible() else "ninguno"
    if elegido == "openai":
        try:
            return await _transcribir_openai(audio, mime)
        except Exception:  # noqa: BLE001 - se intenta el local de respaldo
            _fallos_openai += 1
            if _fallos_openai >= 2:
                _openai_hasta = time.time() + 600
                logger.warning(
                    "OpenAI no responde; se usa el motor local por 10 minutos"
                )
            logger.debug("Falló OpenAI al transcribir", exc_info=True)
            if not disponible():
                return ""
            elegido = "local"
    if _cargando is None:
        _cargando = asyncio.Lock()
    async with _cargando:
        try:
            return await asyncio.to_thread(transcribir_sync, audio, mime)
        except Exception:  # noqa: BLE001 - nunca romper la conversación
            logger.exception("No se pudo transcribir el audio")
            return ""


async def desde_media(media: dict) -> str:
    """Descarga el audio de WhatsApp y lo transcribe."""
    media_id = (media or {}).get("media_id")
    if not media_id:
        return ""
    from ..runtime import whatsapp

    try:
        audio, mime = await whatsapp.download_media(media_id)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo descargar el audio %s", media_id)
        return ""
    return await transcribir(audio, mime or media.get("mime_type") or "audio/ogg")


async def _transcribir_openai(audio: bytes, mime: str) -> str:
    """Transcribe con la API de OpenAI (whisper-1)."""
    import httpx

    base = settings.openai_base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = base + "/audio/transcriptions"
    datos = {
        "model": settings.openai_transcribe_model,
        "language": settings.transcribe_language,
    }
    if settings.openai_transcribe_prompt:
        datos["prompt"] = settings.openai_transcribe_prompt
    archivo = {
        "file": (
            "audio.ogg" if "ogg" in (mime or "") else "audio.m4a",
            audio,
            mime or "audio/ogg",
        )
    }
    async with httpx.AsyncClient(timeout=90) as cliente:
        respuesta = await cliente.post(
            url,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data=datos,
            files=archivo,
        )
    if respuesta.status_code != 200:
        logger.warning(
            "OpenAI no transcribió (%s): %s",
            respuesta.status_code,
            respuesta.text[:200],
        )
        return ""
    return str((respuesta.json() or {}).get("text") or "").strip()
