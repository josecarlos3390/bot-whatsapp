"""Interpretación de imágenes: qué producto hay en la foto.

Usa un modelo con visión por API compatible con OpenAI. Si no hay credencial
de visión configurada, devuelve None y el bot lo dice con honestidad: no
inventa lo que hay en la imagen.
"""

from __future__ import annotations

import base64
import json
import logging

from ..config import settings

logger = logging.getLogger(__name__)

PROMPT = """Analizá la imagen y describí el producto que muestra.
Respondé SOLO un JSON válido, sin explicaciones:
{"objeto": "nombre corto del producto", "categoria": "rubro del hogar o ferretería",
 "marca": "marca visible o cadena vacía", "atributos": "medida, color, material si se ve",
 "descripcion": "una frase breve de lo que se ve"}

Si la imagen no muestra un producto (por ejemplo una persona, un documento o
un paisaje), devolvé {"objeto": "", "categoria": "", "marca": "", "atributos": "", "descripcion": "no es un producto"}.
No inventes marcas ni medidas que no se vean."""


def _credenciales() -> tuple[str, str | None, str] | None:
    """Clave, base y modelo para visión.

    Si no hay una clave dedicada, se usa la misma de DeepSeek: su API
    compatible con OpenAI acepta imágenes en `deepseek-chat`.
    """
    if settings.vision_api_key and settings.vision_model:
        return (
            settings.vision_api_key,
            settings.vision_base_url or None,
            settings.vision_model,
        )
    if settings.deepseek_api_key:
        return (
            settings.deepseek_api_key,
            settings.deepseek_base_url or None,
            settings.vision_model or "deepseek-chat",
        )
    return None


def disponible() -> bool:
    return _credenciales() is not None


async def describe(contenido: bytes, mime: str = "image/jpeg") -> dict | None:
    """Describe el producto de la imagen. None si no hay visión configurada."""
    credenciales = _credenciales()
    if credenciales is None or not contenido:
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:  # pragma: no cover - dependencia opcional
        return None

    api_key, base_url, modelo = credenciales
    cliente = AsyncOpenAI(api_key=api_key, base_url=base_url)
    datos = base64.b64encode(contenido).decode("ascii")
    try:
        respuesta = await cliente.chat.completions.create(
            model=modelo,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{datos}"},
                        },
                    ],
                }
            ],
            temperature=0,
            max_tokens=300,
        )
        texto = (respuesta.choices[0].message.content or "").strip()
        return _parsear(texto)
    except Exception:  # noqa: BLE001 - la visión no debe romper la charla
        logger.exception("Fallo la interpretación de la imagen")
        return None
    finally:
        await cliente.close()


def _parsear(texto: str) -> dict | None:
    """Extrae el JSON de la respuesta del modelo."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = limpio.strip("`")
        if limpio.lower().startswith("json"):
            limpio = limpio[4:]
    inicio = limpio.find("{")
    fin = limpio.rfind("}")
    if inicio < 0 or fin < 0:
        return None
    try:
        datos = json.loads(limpio[inicio : fin + 1])
    except ValueError:
        return None
    if not isinstance(datos, dict):
        return None
    return {
        "objeto": str(datos.get("objeto") or "").strip()[:80],
        "categoria": str(datos.get("categoria") or "").strip()[:60],
        "marca": str(datos.get("marca") or "").strip()[:40],
        "atributos": str(datos.get("atributos") or "").strip()[:120],
        "descripcion": str(datos.get("descripcion") or "").strip()[:200],
    }
