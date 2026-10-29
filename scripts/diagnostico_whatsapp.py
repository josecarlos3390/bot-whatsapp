"""Diagnóstico del envío de WhatsApp: token, número y un envío de prueba."""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings


async def estado_numero() -> tuple[int, str]:
    url = (
        f"https://graph.facebook.com/{settings.wa_graph_version}/"
        f"{settings.wa_phone_number_id}"
    )
    async with httpx.AsyncClient(timeout=20) as cliente:
        respuesta = await cliente.get(
            url,
            params={
                "fields": (
                    "display_phone_number,verified_name,"
                    "quality_rating,status,code_verification_status"
                )
            },
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
        )
    return respuesta.status_code, respuesta.text


async def main() -> int:
    print("configuración")
    print("  dry_run:", settings.wa_dry_run)
    print("  phone_number_id:", settings.wa_phone_number_id)
    print("  graph:", settings.wa_graph_version)
    print("  token presente:", bool(settings.wa_access_token))

    codigo, cuerpo = await estado_numero()
    print("\nestado del número:", codigo)
    print(" ", cuerpo[:400])

    if codigo != 200:
        print("\nEl token o el número no están operativos.")
        return 1

    destino = "59169006969"
    print(f"\nenvío de prueba a {destino}")
    url = (
        f"https://graph.facebook.com/{settings.wa_graph_version}/"
        f"{settings.wa_phone_number_id}/messages"
    )
    async with httpx.AsyncClient(timeout=20) as cliente:
        respuesta = await cliente.post(
            url,
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": destino,
                "type": "text",
                "text": {
                    "body": (
                        "Prueba de diagnóstico del bot. "
                        "Si recibís este mensaje, el envío funciona."
                    )
                },
            },
        )
    print(" respuesta:", respuesta.status_code, respuesta.text[:400])
    return 0 if respuesta.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
