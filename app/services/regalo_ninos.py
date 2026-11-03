"""Regalos para chicos: preguntar la edad antes de recomendar.

«Quiero algo para mis hijos» no dice edad ni qué le gusta. Sin ese dato el
bot termina mostrando un juego de batería para un bebé. Primero se pregunta
para quién y qué edad, y recién después se busca.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog

# «para mis hijos», «algo para mi nena», «un regalo para mi nieto»…
HIJOS = re.compile(
    r"\b(mis?\s+)?(hijos?|hijas?|nietos?|nietas?|sobrinos?|sobrinas?|"
    r"ninos?|niñas?|ninas?|nenes?|nenas?|bebes?|bebés?|chicos?|chicas?|"
    r"criaturas?|peques?)\b",
    re.IGNORECASE,
)

# Si ya nombró el producto, no hace falta preguntar la edad.
CONCRETO = re.compile(
    r"\b(mu[ñn]ecas?|peluches?|juguetes?|lego|rompecabezas|"
    r"autitos?|carritos?|bicicleta|triciclo|pelota|ajedrez|backgammon)\b",
    re.IGNORECASE,
)

REGALO = re.compile(
    r"\b(regalo|regalar|obsequio|sorpresa)\b", re.IGNORECASE
)

EDADES = {
    "0-2": "0 a 2 años",
    "3-5": "3 a 5 años",
    "6-9": "6 a 9 años",
    "10+": "más de 9 años",
}

# Qué buscar según la edad.
BUSQUEDA = {
    "0-2": ("peluche", "muñeca bebé", "sonajero"),
    "3-5": ("muñeca", "peluche", "juego"),
    "6-9": ("juego", "peluche", "muñeca"),
    "10+": ("juego de mesa", "backgammon", "ajedrez"),
}


def es_pedido(texto: str) -> bool:
    """¿Pide algo para chicos sin decir qué producto?"""
    crudo = (texto or "").strip()
    if not crudo:
        return False
    if CONCRETO.search(crudo):
        return False
    return bool(HIJOS.search(crudo) or REGALO.search(crudo))


def pregunta() -> str:
    return (
        "¡Me encanta! Para acertar con el regalo, ¿para qué edad es? 🎁\n"
        "Tocá una opción o escribime la edad."
    )


def botones() -> list[dict[str, str]]:
    return [
        {"id": "kidsage:0-2", "title": "0 a 2 años"},
        {"id": "kidsage:3-5", "title": "3 a 5 años"},
        {"id": "kidsage:6-9", "title": "6 a 9 años"},
    ]


def leer_edad(valor: str) -> str | None:
    """Convierte lo que escribió el cliente en un rango."""
    crudo = (valor or "").strip().lower()
    if crudo in EDADES:
        return crudo
    numero = re.search(r"\b(\d{1,2})\b", crudo)
    if numero is None:
        return None
    edad = int(numero.group(1))
    if edad <= 2:
        return "0-2"
    if edad <= 5:
        return "3-5"
    if edad <= 9:
        return "6-9"
    return "10+"


def rango_de(valor: str) -> str | None:
    """Acepta el id del botón (`kidsage:3-5`) o el texto del botón."""
    crudo = (valor or "").strip()
    if crudo.lower().startswith("kidsage:"):
        crudo = crudo.split(":", 1)[1]
    return leer_edad(crudo)


async def buscar(session: AsyncSession, rango: str) -> dict:
    """Busca opciones para esa edad y arma la respuesta."""
    terminos = BUSQUEDA.get(rango, BUSQUEDA["6-9"])
    vistos: set[str] = set()
    opciones = []
    for termino in terminos:
        for item in await catalog.search_items(session, termino, limit=3):
            if item.sku in vistos:
                continue
            vistos.add(item.sku)
            opciones.append(item)
        if len(opciones) >= 4:
            break

    etiqueta = EDADES.get(rango, "esa edad")
    if not opciones:
        return {
            "texto": (
                f"Para {etiqueta} no tengo juguetes con stock en este "
                "momento 😕\n"
                "¿Querés que te muestre algo para el cuarto o para la casa?"
            ),
            "items": [],
        }
    return {
        "texto": (
            f"Para {etiqueta} encontré {len(opciones)} opciones 🎁\n"
            "Si ninguno cierra, decime qué le gusta y busco otra cosa."
        ),
        "items": opciones,
    }
