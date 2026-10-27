"""¿VTEX nos da palabras clave para clasificar productos?

Revisa lo que expone el integrador y mide cuánta señal de clasificación hay
en los datos actuales (especificaciones, descripción, nombre completo).
"""

from __future__ import annotations

import argparse
import asyncio
import re
from collections import Counter

import httpx

from app.config import settings

CAMPOS_CLAVE = ("key", "meta", "tag", "seo", "spec", "title", "description", "categor")


def _limpiar_html(texto: str) -> str:
    return re.sub(r"<[^>]+>", " ", texto or "").strip()


async def revisar(limit: int = 40) -> dict:
    base = settings.sap_paas_url.rstrip("/")
    headers = {"X-Api-Key": settings.sap_paas_api_key}
    async with httpx.AsyncClient(timeout=40) as cliente:
        respuesta = await cliente.get(
            f"{base}/api/vtex/items/export",
            params={"limit": max(1, min(limit, 200))},
            headers=headers,
        )
        respuesta.raise_for_status()
        items = respuesta.json()
    if not isinstance(items, list):
        items = []

    campos: Counter = Counter()
    specs: Counter = Counter()
    con_specs = 0
    con_descripcion = 0
    con_nombre_completo = 0
    for item in items:
        campos.update(item.keys())
        if isinstance(item.get("specifications"), dict) and item["specifications"]:
            con_specs += 1
            specs.update(item["specifications"].keys())
        if _limpiar_html(item.get("description") or ""):
            con_descripcion += 1
        if item.get("name_complete") and item["name_complete"] != item.get("name"):
            con_nombre_completo += 1

    total = len(items) or 1
    return {
        "items": len(items),
        "campos": campos,
        "tiene_keywords": "keywords" in campos or "KeyWords" in campos,
        "tiene_seo": any(
            campo for campo in campos if any(clave in campo.lower() for clave in CAMPOS_CLAVE)
        ),
        "con_specs": con_specs,
        "spec_keys": specs.most_common(12),
        "con_descripcion": con_descripcion,
        "con_nombre_completo": con_nombre_completo,
        "porcentaje_specs": round(con_specs / total * 100, 1),
        "porcentaje_descripcion": round(con_descripcion / total * 100, 1),
    }


def informe(datos: dict) -> str:
    lineas = [
        "¿VTEX nos da palabras clave?",
        f"Productos revisados: {datos['items']}",
        "",
        f"Campos que expone el integrador: {', '.join(sorted(datos['campos']))}",
        "",
        f"Campo 'keywords' en el export: {'sí' if datos['tiene_keywords'] else 'NO'}",
        f"Campos tipo SEO/etiquetas: {'sí' if datos['tiene_seo'] else 'no'}"
        if not datos["tiene_keywords"]
        else "",
        "",
        f"Con especificaciones: {datos['con_specs']} "
        f"({datos['porcentaje_specs']} %)",
        f"Con descripción: {datos['con_descripcion']} "
        f"({datos['porcentaje_descripcion']} %)",
        f"Con nombre completo distinto: {datos['con_nombre_completo']}",
        "",
        "Especificaciones más frecuentes:",
    ]
    for clave, veces in datos["spec_keys"]:
        lineas.append(f"- {clave}: {veces}")
    lineas += [
        "",
        "Conclusión:",
    ]
    if datos["tiene_keywords"]:
        lineas.append(
            "- VTEX expone palabras clave: conviene usarlas como señal principal."
        )
    else:
        lineas.append(
            "- El export NO trae el campo KeyWords de VTEX. Para tenerlo hay que"
        )
        lineas.append(
            "  pedirle al integrador que lo incluya (o usar la API de catálogo)."
        )
    lineas.append(
        "- Mientras tanto, las especificaciones (Tipo, Color, Material, Uso) y la"
    )
    lineas.append(
        "  descripción son la mejor señal disponible para clasificar."
    )
    return "\n".join(linea for linea in lineas if linea != "")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    datos = await revisar(args.limit)
    print(informe(datos))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
