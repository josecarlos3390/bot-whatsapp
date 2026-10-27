"""Descarga de archivos que llegan por WhatsApp (imágenes y documentos)."""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def download(media_id: str) -> tuple[bytes, str] | None:
    """Baja un archivo de Meta y devuelve (contenido, tipo MIME)."""
    if not media_id or not settings.wa_access_token:
        return None
    base = f"https://graph.facebook.com/{settings.wa_graph_version}"
    headers = {"Authorization": f"Bearer {settings.wa_access_token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            meta = await cliente.get(f"{base}/{media_id}", headers=headers)
            if meta.status_code != 200:
                logger.warning(
                    "No se pudo resolver el archivo %s: %s",
                    media_id,
                    meta.status_code,
                )
                return None
            datos = meta.json()
            url = datos.get("url")
            mime = datos.get("mime_type") or "application/octet-stream"
            if not url:
                return None
            archivo = await cliente.get(url, headers=headers)
            if archivo.status_code != 200:
                logger.warning(
                    "No se pudo descargar el archivo %s: %s",
                    media_id,
                    archivo.status_code,
                )
                return None
            return archivo.content, mime
    except httpx.HTTPError:
        logger.exception("Error de red al bajar el archivo %s", media_id)
        return None
