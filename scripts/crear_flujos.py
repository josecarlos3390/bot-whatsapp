"""Crear y publicar los WhatsApp Flows del checkout.

Lee los JSON de `docs/flows/`, crea un Flow en la cuenta de WhatsApp, sube el
asset y lo publica. Los IDs quedan en el `.env`.

Uso:
    python -m scripts.crear_flujos            # muestra qué haría
    python -m scripts.crear_flujos --aplicar  # crea y publica
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from app.config import settings

# archivo del repo -> clave del .env
FLUJOS = {
    "facturacion-tienda.json": "WA_FLOW_FACTURACION",
    "datos-entrega-domicilio.json": "WA_FLOW_ENTREGA",
}
CARPETA = Path("docs/flows")


async def crear(cliente: httpx.AsyncClient, nombre: str, json_flujo: Path) -> str:
    r = await cliente.post(
        f"https://graph.facebook.com/{settings.wa_graph_version}/"
        f"{settings.wa_waba_id}/flows",
        headers={"Authorization": f"Bearer {settings.wa_access_token}"},
        json={"name": nombre, "categories": ["OTHER"]},
    )
    r.raise_for_status()
    flow_id = r.json()["id"]

    with json_flujo.open("rb") as archivo:
        subida = await cliente.post(
            f"https://graph.facebook.com/{settings.wa_graph_version}/"
            f"{flow_id}/assets",
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            data={"name": "flow.json", "asset_type": "FLOW_JSON"},
            files={"file": ("flow.json", archivo, "application/json")},
        )
    subida.raise_for_status()
    errores = (subida.json() or {}).get("validation_errors") or []
    if errores:
        raise SystemExit(f"El JSON de {nombre} tiene errores: {errores[:2]}")

    publicacion = await cliente.post(
        f"https://graph.facebook.com/{settings.wa_graph_version}/{flow_id}/publish",
        headers={"Authorization": f"Bearer {settings.wa_access_token}"},
    )
    publicacion.raise_for_status()
    return flow_id


def guardar_env(valores: dict[str, str]) -> None:
    env = Path(".env")
    lineas = env.read_text(encoding="utf-8").splitlines()
    for clave, valor in valores.items():
        reemplazada = False
        for indice, linea in enumerate(lineas):
            if linea.startswith(f"{clave}="):
                lineas[indice] = f"{clave}={valor}"
                reemplazada = True
                break
        if not reemplazada:
            lineas.append(f"{clave}={valor}")
    env.write_text("\n".join(lineas) + "\n", encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    for archivo in FLUJOS:
        ruta = CARPETA / archivo
        if not ruta.exists():
            print(f"falta {ruta}")
            return 1

    if not args.aplicar:
        print("Flujos a crear:")
        for archivo, clave in FLUJOS.items():
            print(f"  · {archivo} → {clave}")
        print("\nSimulación: no se creó nada. Para aplicar: --aplicar")
        return 0

    ids: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=120) as cliente:
        for archivo, clave in FLUJOS.items():
            nombre = Path(archivo).stem.replace("-", " ").capitalize()
            flow_id = await crear(cliente, nombre, CARPETA / archivo)
            ids[clave] = flow_id
            print(f"✓ {nombre}: {flow_id}")

    guardar_env(ids)
    print("\n✓ IDs guardados en .env")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
