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
        **_atributos(getattr(item, "attributes", None), getattr(item, "keywords", None)),
    }


def _atributos(attributes: Any, keywords: str | None) -> dict:
    data: dict = {}
    if isinstance(attributes, dict):
        specs = attributes.get("specs")
        if isinstance(specs, dict) and specs:
            data["specs"] = dict(list(specs.items())[:6])
        for clave, alias in SPEC_ALIASES.items():
            valor = attributes.get(clave) or _spec_value(specs, alias)
            if valor:
                data[clave] = valor
        if attributes.get("seo_title"):
            data["seo_title"] = attributes["seo_title"]
    if keywords:
        data["keywords"] = keywords
    return data


def enrich(data: dict, item) -> dict:
    """Suma al diccionario los atributos y keywords del artículo."""
    data.update(_atributos(getattr(item, "attributes", None), getattr(item, "keywords", None)))
    return data
