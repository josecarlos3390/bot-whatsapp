"""Prueba real con audio e imagen, no simulados.

Genera notas de voz en español (edge-tts), las convierte al formato de
WhatsApp (OGG/Opus) y las pasa por el camino real: transcripción → bot.
Para las imágenes baja fotos reales del catálogo y las pasa por la visión.

Uso:
    python -m scripts.prueba_audio_imagen
    python -m scripts.prueba_audio_imagen --solo audio
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx

from app.db import SessionLocal
from app.models import Contact, Conversation
from app.services import ingest, media as media_service, vision

AUDIOS = [
    ("licuadora", "Hola, busco una licuadora para mi casa, algo no muy caro."),
    ("envio", "Buenas, ¿hacen envíos a Santa Cruz y cuánto cuesta?"),
    ("devolucion", "Compré una licuadora y me llegó rota, quiero cambiarla."),
    ("colchon", "Necesito un colchón de dos plazas, ¿qué me recomendás?"),
]

IMAGENES = ["licuadora", "televisor", "taladro", "colchon"]


def _texto(mensaje) -> str:
    if isinstance(mensaje, dict):
        return mensaje.get("text") or ""
    return getattr(mensaje, "text", "") or ""


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


async def _voz(texto: str, destino: Path) -> Path:
    """Genera la nota de voz en OGG/Opus (formato de WhatsApp)."""
    import edge_tts

    mp3 = destino.with_suffix(".mp3")
    await edge_tts.Communicate(texto, "es-BO-SofiaNeural").save(str(mp3))
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-i",
            str(mp3),
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(destino),
        ],
        capture_output=True,
        check=True,
    )
    mp3.unlink(missing_ok=True)
    return destino


async def _contacto(session, nombre: str) -> Contact:
    numero = f"5917{uuid.uuid4().hex[:8]}"
    contacto = Contact(wa_id=numero, phone_e164=f"+{numero}", name=nombre)
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def probar_audio(session, texto: str, etiqueta: str) -> tuple[str, str]:
    """Nota de voz → transcripción → respuesta del bot."""
    with tempfile.TemporaryDirectory() as carpeta:
        destino = Path(carpeta) / f"{etiqueta}.ogg"
        await _voz(texto, destino)
        audio = destino.read_bytes()

    from app.services import transcription

    dicho = await transcription.transcribir(audio, "audio/ogg")

    contacto = await _contacto(session, f"Voz {etiqueta}")
    # Se pasa la transcripción como la deja el webhook en producción.
    salida = await ingest.ingest_inbound(
        session,
        contacto.wa_id,
        dicho,
        f"wamid.{uuid.uuid4().hex[:10]}",
        name=contacto.name,
        deliver=False,
        media={"media_id": "voz", "kind": "audio", "transcripcion": dicho},
    )
    respuesta = " | ".join(
        (_texto(m)).replace("\n", " ") for m in salida if _texto(m)
    )
    return dicho, respuesta[:220]


async def _imagen_de(termino: str) -> tuple[bytes, str, str] | None:
    """Baja una foto real del catálogo para el término pedido."""
    from app.services import catalog

    async with SessionLocal() as session:
        filas = await catalog.search_items(session, termino, limit=5)
        for fila in filas:
            info = await catalog.primary_image_info(session, fila.sku)
            url = (info or {}).get("url") or ""
            if not url:
                continue
            try:
                async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                    respuesta = await c.get(url)
                if respuesta.status_code == 200 and respuesta.content:
                    return respuesta.content, "image/jpeg", fila.name
            except Exception:  # noqa: BLE001 - se prueba la siguiente foto
                continue
    return None


async def probar_imagen(session, termino: str) -> tuple[str, str, str]:
    """Foto real → visión → respuesta del bot."""
    datos = await _imagen_de(termino)
    if datos is None:
        return termino, "(sin imagen en el catálogo)", ""
    contenido, mime, nombre = datos
    descripcion = await vision.describe(contenido, mime)
    if descripcion is None:
        return nombre, "(la visión no respondió)", ""

    contacto = await _contacto(session, f"Foto {termino}")
    original = media_service.download
    original_vision = vision.describe

    async def _descarga(media_id: str):
        return contenido, mime

    async def _vision(archivo, tipo):
        return descripcion

    media_service.download = _descarga  # type: ignore[assignment]
    vision.describe = _vision  # type: ignore[assignment]
    try:
        salida = await ingest.ingest_inbound(
            session,
            contacto.wa_id,
            "",
            f"wamid.{uuid.uuid4().hex[:10]}",
            name=contacto.name,
            deliver=False,
            media={"media_id": "foto", "kind": "image"},
        )
    finally:
        media_service.download = original  # type: ignore[assignment]
        vision.describe = original_vision  # type: ignore[assignment]
    respuesta = " | ".join(
        (_texto(m)).replace("\n", " ") for m in salida if _texto(m)
    )
    return nombre, str(descripcion), respuesta[:220]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solo", default="", choices=["", "audio", "imagen"])
    args = parser.parse_args()

    async with SessionLocal() as session:
        if args.solo in {"", "audio"}:
            print("AUDIO (voz real → transcripción → bot)")
            for etiqueta, texto in AUDIOS:
                dicho, respuesta = await probar_audio(session, texto, etiqueta)
                print(f"\n  dicho:      {texto}")
                print(f"  transcripción: {dicho}")
                print(f"  respuesta:  {respuesta}")

        if args.solo in {"", "imagen"}:
            print("\nIMAGEN (foto real del catálogo → visión → bot)")
            for termino in IMAGENES:
                nombre, descripcion, respuesta = await probar_imagen(
                    session, termino
                )
                print(f"\n  foto de:     {termino} ({nombre[:40]})")
                print(f"  visión:      {descripcion}")
                print(f"  respuesta:   {respuesta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
