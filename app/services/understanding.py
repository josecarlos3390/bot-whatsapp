"""Comprensión del mensaje con el modelo antes de decidir.

Devuelve una lectura corta y estructurada (intención, producto, atributos,
orden de precio) para que el bot no dependa solo de reglas fijas. Se cachea
por texto: el mismo mensaje repetido no vuelve a costar una llamada.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict

from ..config import settings

logger = logging.getLogger(__name__)

_CACHE: "OrderedDict[str, dict | None]" = OrderedDict()
_CACHE_SIZE = 400

_SALTOS = re.compile(r"^(hola|buenas|buen d[ií]a|gracias|ok|dale|s[ií]|no)$", re.I)

PROMPT = """Sos el intérprete de un chatbot de ventas de un homecenter.
Leé el mensaje del cliente y devolvé SOLO un JSON con esta forma:
{"intencion": "saludo|producto|precio|comparacion|envio|devolucion|garantia|humano|otro",
 "producto": "rubro o producto en singular, o null",
 "atributos": ["medida, color, material, marca u otra condición"],
 "orden_precio": "asc|desc|null",
 "referencia": "ultimo|null"}

Reglas:
- "orden_precio" es "asc" si pide lo más barato/económico o el menor precio,
  "desc" si pide lo más caro.
- "producto" es el sustantivo que busca ("taladro", "espejo", "colchón").
  Si solo dice "el más barato" sin nombrarlo, usá null.
- "referencia" es "ultimo" si se refiere a algo ya mostrado ("ese", "el mismo",
  "cuál es el más barato").
- No inventes productos que no menciona.
"""


def _clave(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:200]


def _limpiar(datos: dict) -> dict | None:
    if not isinstance(datos, dict):
        return None
    intencion = str(datos.get("intencion") or "otro").lower()
    if intencion not in {
        "saludo", "producto", "precio", "comparacion", "envio",
        "devolucion", "garantia", "humano", "otro",
    }:
        intencion = "otro"
    producto = datos.get("producto")
    producto = str(producto).strip().lower() if producto else None
    atributos = [
        str(item).strip().lower()
        for item in (datos.get("atributos") or [])
        if str(item).strip()
    ][:4]
    orden = str(datos.get("orden_precio") or "").lower()
    if orden not in {"asc", "desc"}:
        orden = None
    referencia = "ultimo" if str(datos.get("referencia") or "").lower() == "ultimo" else None
    return {
        "intencion": intencion,
        "producto": producto,
        "atributos": atributos,
        "orden_precio": orden,
        "referencia": referencia,
    }


async def parse(client, text: str) -> dict | None:
    """Interpretación del mensaje. None si no hay modelo o falla."""
    if not settings.deepseek_api_key or client is None:
        return None
    clave = _clave(text)
    if not clave or _SALTOS.match(clave):
        return None
    if clave in _CACHE:
        _CACHE.move_to_end(clave)
        return _CACHE[clave]

    try:
        respuesta = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": text[:400]},
            ],
            temperature=0,
            max_tokens=150,
            extra_body={"thinking": {"type": "disabled"}},
        )
        from . import ai_usage

        ai_usage.registrar(
            "lectura", getattr(respuesta, "usage", None),
            modelo=settings.deepseek_model,
        )
        contenido = respuesta.choices[0].message.content or ""
        inicio = contenido.find("{")
        datos = json.loads(contenido[inicio:]) if inicio >= 0 else None
        resultado = _limpiar(datos) if datos else None
    except Exception:  # noqa: BLE001 - la comprensión nunca rompe la charla
        logger.debug("No se pudo interpretar el mensaje", exc_info=True)
        resultado = None

    _CACHE[clave] = resultado
    if len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return resultado


def clear_cache() -> None:
    _CACHE.clear()
