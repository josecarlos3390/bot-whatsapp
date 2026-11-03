"""Revisar respuestas del bot buscando incoherencias.

Tres bugs reales que llegaron de chats de prueba:

- «No tengo *hot wheels* exactamente» cuando el catálogo **sí** los tiene.
- Abrir la ficha de un *estuche para autos* cuando el cliente pidió
  *un auto a escala*.
- Decir «no tengo productos para *munecas*» porque la búsqueda perdía la ñ.

Los tres se detectan comparando la respuesta con el catálogo y con el
mensaje del cliente. Este módulo junta esas comprobaciones para usarlas en
tests y en la auditoría de conversaciones reales.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .catalog import QUERY_STOPWORDS, _fold

# «No tengo X», «no encontré X», «no hay X»
NO_TENGO = re.compile(
    r"\bno\s+(?:tengo|encontr[eé]|hay|manejamos|tenemos)\b[^.\n]{0,60}",
    re.IGNORECASE,
)


def palabras(texto: str) -> list[str]:
    """Palabras con contenido (sin saludos ni relleno)."""
    salida = []
    for trozo in re.split(r"\W+", texto or ""):
        if not trozo:
            continue
        limpia = _fold(trozo)
        if limpia in QUERY_STOPWORDS or len(limpia) < 3:
            continue
        salida.append(limpia)
    return salida


def niega_tenencia(respuesta: str) -> str | None:
    """Devuelve el fragmento donde el bot dice que no tiene algo."""
    coincidencia = NO_TENGO.search(respuesta or "")
    return coincidencia.group(0) if coincidencia else None


async def hay_en_catalogo(
    session: AsyncSession, termino: str, limite: int = 1
) -> bool:
    """¿El catálogo tiene algo para ese término?"""
    if not termino.strip():
        return False
    return bool(await catalog.search_items(session, termino, limit=limite))


async def contradice_al_catalogo(
    session: AsyncSession, mensaje: str, respuesta: str
) -> dict | None:
    """El bot dice «no tengo X» pero el catálogo tiene X.

    Devuelve el detalle del hallazgo o None.
    """
    fragmento = niega_tenencia(respuesta)
    if fragmento is None:
        return None
    terminos = palabras(mensaje)
    if not terminos:
        return None
    consulta = " ".join(terminos[:3])
    if not await hay_en_catalogo(session, consulta):
        return None
    return {
        "tipo": "niega_tenencia",
        "mensaje": mensaje,
        "fragmento": fragmento.strip(),
        "consulta": consulta,
    }


def ficha_ajena(mensaje: str, nombre_producto: str) -> dict | None:
    """La ficha mostrada no tiene que ver con lo que pidió el cliente."""
    propios = palabras(mensaje)
    if not propios or not nombre_producto:
        return None
    nombre = _fold(nombre_producto)
    faltan = [palabra for palabra in propios if palabra not in nombre]
    if not faltan or len(faltan) == len(propios):
        # Si no falta ninguna encaja; si faltan todas, el mensaje no hablaba
        # de producto (un «hola» no se evalúa).
        return None
    return {
        "tipo": "ficha_ajena",
        "mensaje": mensaje,
        "producto": nombre_producto,
        "faltan": faltan,
    }


def pregunto_sin_mostrar(respuesta: str, productos: int = 0) -> dict | None:
    """Preguntó algo en vez de mostrar lo que ya tenía disponible."""
    texto = (respuesta or "").strip()
    if not texto.endswith("?"):
        return None
    if productos:
        return None
    return {"tipo": "pregunta_sin_productos", "respuesta": texto[:120]}

async def existe_producto(session: AsyncSession, texto: str) -> bool:
    """¿El cliente nombró un producto que existe de verdad?

    Más estricto que una búsqueda: exige que el nombre del artículo contenga
    todas las palabras con contenido del mensaje.
    """
    terminos = palabras(texto)
    if len(terminos) < 2:
        return False
    consulta = " ".join(terminos[:3])
    candidatos = await catalog.search_items(session, consulta, limit=8)
    return any(catalog.nombra_todos(item, consulta) for item in candidatos)
