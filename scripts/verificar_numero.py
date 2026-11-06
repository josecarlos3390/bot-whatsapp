"""Verificar el estado de un número de WhatsApp Business.

Consulta la API de Meta (solo lectura) y dice si el número sirve para el bot.

Uso:
    python -m scripts.verificar_numero              # el del .env
    python -m scripts.verificar_numero --id 123456789
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from app.config import settings

CAMPOS = (
    "display_phone_number,verified_name,status,"
    "code_verification_status,quality_rating"
)


async def consultar(numero_id: str) -> tuple[int, dict]:
    url = f"https://graph.facebook.com/{settings.wa_graph_version}/{numero_id}"
    async with httpx.AsyncClient(timeout=20) as cliente:
        respuesta = await cliente.get(
            url,
            params={"fields": CAMPOS},
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
        )
    try:
        datos = respuesta.json()
    except ValueError:
        datos = {}
    return respuesta.status_code, datos


def veredicto(datos: dict) -> list[str]:
    """Qué falta para poder usar el número."""
    faltan: list[str] = []
    if datos.get("status") != "CONNECTED":
        faltan.append(f"estado {datos.get('status')} (debe ser CONNECTED)")
    verificacion = datos.get("code_verification_status")
    if verificacion not in {"VERIFIED", "NOT_APPLICABLE"}:
        faltan.append(f"verificación {verificacion} (debe ser VERIFIED)")
    calidad = datos.get("quality_rating")
    if calidad in {"RED", "YELLOW"}:
        faltan.append(f"calidad {calidad} (conviene GREEN)")
    return faltan


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default=settings.wa_phone_number_id)
    args = parser.parse_args()

    if not args.id:
        print("Falta el identificador del número (--id).")
        return 1
    if not settings.wa_access_token:
        print("Falta WA_ACCESS_TOKEN en el .env.")
        return 1

    print(f"Número configurado: {args.id}")
    codigo, datos = await consultar(args.id)
    if codigo != 200:
        print(f"\n✗ La API respondió {codigo}")
        print(f"  {str(datos)[:300]}")
        if codigo == 401:
            print("  El token no sirve o venció.")
        elif codigo == 400:
            print("  El identificador del número es inválido.")
        return 1

    print("\nDatos del número")
    print(f"  · teléfono     {datos.get('display_phone_number')}")
    print(f"  · nombre       {datos.get('verified_name')}")
    print(f"  · estado       {datos.get('status')}")
    print(f"  · verificación {datos.get('code_verification_status')}")
    print(f"  · calidad      {datos.get('quality_rating')}")

    faltan = veredicto(datos)
    if not faltan:
        print("\n✓ El número está listo para el bot.")
        return 0
    print("\n✗ Todavía no está listo:")
    for motivo in faltan:
        print(f"  · {motivo}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
