"""Cómo se expone un artículo del catálogo hacia el bot y el modelo.

Un solo lugar arma el diccionario del producto: antes la búsqueda, la ficha
y la comparación lo construían por separado y un campo nuevo se agregaba en
una y se olvidaba en otra.
"""

from __future__ import annotations

from typing import Any

# De dónde sale cada atributo si VTEX no lo trae como campo propio.
SPEC_ALIASES: dict[str, tuple[str, ...]] = {
    "product_type": ("Tipo", "Type"),
    "color": ("Color",),
    "material": ("Material",),
}


def _spec_value(specs: Any, names: tuple[str, ...]) -> str | None:
    if not isinstance(specs, dict):
        return None
    plegado = {str(key).strip().lower(): value for key, value in specs.items()}
    for name in names:
        valor = plegado.get(name.lower())
        if valor:
            return str(valor)
    return None


def payload(item) -> dict:
    """Datos base del artículo (sin precio ni promociones)."""
    return {
        "sku": item.sku,
        "name": item.name,
        "price": str(item.price),
        "currency": item.currency,
        "stock": item.stock,
        "category": getattr(item, "category", None),
        "brand": getattr(item, "brand", None),
        "image_url": getattr(item, "image_url", None),
        "description": getattr(item, "description", None),
        **_atributos(item),
    }


def atributo(item, clave: str) -> str | None:
    """Valor de un atributo: columna propia y, si falta, el JSON."""
    valor = getattr(item, clave, None)
    if valor:
        return str(valor)
    attributes = getattr(item, "attributes", None)
    if isinstance(attributes, dict):
        directo = attributes.get(clave)
        if directo:
            return str(directo)
        return _spec_value(attributes.get("specs"), SPEC_ALIASES.get(clave, ()))
    return None


def _atributos(item) -> dict:
    data: dict = {}
    attributes = getattr(item, "attributes", None)
    if isinstance(attributes, dict):
        specs = attributes.get("specs")
        if isinstance(specs, dict) and specs:
            data["specs"] = dict(list(specs.items())[:6])
        if attributes.get("seo_title"):
            data["seo_title"] = attributes["seo_title"]
    for clave in SPEC_ALIASES:
        valor = atributo(item, clave)
        if valor:
            data[clave] = valor
    keywords = getattr(item, "keywords", None)
    if keywords:
        data["keywords"] = keywords
    return data


def enrich(data: dict, item) -> dict:
    """Suma al diccionario los atributos y keywords del artículo."""
    data.update(_atributos(item))
    return data
