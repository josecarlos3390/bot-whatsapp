"""Apuntar el webhook de Meta a la URL pública actual del bot.

El túnel de Cloudflare cambia de URL al reiniciar, y Meta sigue apuntando a la
vieja: el bot queda sordo sin que nada falle a la vista. Este script deja la
suscripción de la app al día.

Uso:
    python -m scripts.actualizar_webhook            # muestra qué haría
    python -m scripts.actualizar_webhook --aplicar  # lo aplica
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from app.config import settings

APP_ID = "2438463666347806"
OBJETO = "whatsapp_business_account"
CAMPOS = "messages"


def url_del_webhook() -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/webhooks/whatsapp" if base else ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    url = url_del_webhook()
    if not url:
        print("Falta PUBLIC_BASE_URL en el .env.")
        return 1
    if not settings.wa_app_secret:
        print("Falta WA_APP_SECRET en el .env (Configuración básica de la app).")
        return 1

    print(f"App          : {APP_ID}")
    print(f"Webhook      : {url}")
    print(f"Token verif. : {settings.wa_verify_token[:4]}…")
    print(f"Campos       : {CAMPOS}")

    if not args.aplicar:
        print("\nSimulación: no se llamó a Meta. Para aplicar: --aplicar")
        return 0

    datos = {
        "object": OBJETO,
        "callback_url": url,
        "verify_token": settings.wa_verify_token,
        "fields": CAMPOS,
        "access_token": f"{APP_ID}|{settings.wa_app_secret}",
    }
    async with httpx.AsyncClient(timeout=40) as cliente:
        respuesta = await cliente.post(
            f"https://graph.facebook.com/{settings.wa_graph_version}/"
            f"{APP_ID}/subscriptions",
            data=datos,
        )
        print(f"\nMeta respondió {respuesta.status_code}: {respuesta.text[:200]}")

        consulta = await cliente.get(
            f"https://graph.facebook.com/{settings.wa_graph_version}/"
            f"{APP_ID}/subscriptions",
            params={
                "object": OBJETO,
                "access_token": f"{APP_ID}|{settings.wa_app_secret}",
            },
        )
        print(f"Suscripción actual: {consulta.text[:400]}")

    return 0 if respuesta.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
