"""Revisar si la app de WhatsApp está lista para pasar a producción.

Comprueba número, webhook y los datos de la app que Meta exige publicar.
No cambia nada.

Uso:
    python -m scripts.verificar_produccion
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import settings

APP_ID = "2438463666347806"


def marca(ok: bool) -> str:
    return "✓" if ok else "✗"


async def numero(cliente: httpx.AsyncClient) -> dict:
    r = await cliente.get(
        f"https://graph.facebook.com/{settings.wa_graph_version}/"
        f"{settings.wa_phone_number_id}",
        params={"fields": "display_phone_number,verified_name,status,"
                          "code_verification_status,quality_rating"},
        headers={"Authorization": f"Bearer {settings.wa_access_token}"},
    )
    return r.json() if r.status_code == 200 else {}


async def app_info(cliente: httpx.AsyncClient) -> dict:
    if not settings.wa_app_secret:
        return {}
    r = await cliente.get(
        f"https://graph.facebook.com/{settings.wa_graph_version}/{APP_ID}",
        params={
            "fields": "name,privacy_policy_url,category,link,icon_url",
            "access_token": f"{APP_ID}|{settings.wa_app_secret}",
        },
    )
    return r.json() if r.status_code == 200 else {}


async def webhook(cliente: httpx.AsyncClient) -> dict:
    if not settings.wa_app_secret:
        return {}
    r = await cliente.get(
        f"https://graph.facebook.com/{settings.wa_graph_version}/"
        f"{APP_ID}/subscriptions",
        params={
            "object": "whatsapp_business_account",
            "access_token": f"{APP_ID}|{settings.wa_app_secret}",
        },
    )
    datos = (r.json() or {}).get("data") or []
    return datos[0] if datos else {}


async def main() -> int:
    async with httpx.AsyncClient(timeout=30) as cliente:
        datos_numero = await numero(cliente)
        datos_app = await app_info(cliente)
        datos_hook = await webhook(cliente)

    print("Número")
    print(f"  {marca(datos_numero.get('status') == 'CONNECTED')} "
          f"estado: {datos_numero.get('status')}")
    print(f"  {marca(datos_numero.get('code_verification_status') == 'VERIFIED')} "
          f"verificación: {datos_numero.get('code_verification_status')}")
    print(f"    teléfono: {datos_numero.get('display_phone_number')}")
    print(f"    nombre:   {datos_numero.get('verified_name')}")

    print("\nWebhook")
    campos = [c.get("name") for c in datos_hook.get("fields", [])]
    print(f"  {marca(bool(datos_hook.get('active')))} activo")
    print(f"  {marca('messages' in campos)} campo messages")
    print(f"    URL: {datos_hook.get('callback_url')}")
    print(f"    campos: {len(campos)}")

    print("\nApp")
    print(f"  {marca(bool(datos_app.get('privacy_policy_url')))} "
          f"política de privacidad: {datos_app.get('privacy_policy_url') or '(falta)'}")
    print(f"  {marca(bool(datos_app.get('category')))} "
          f"categoría: {datos_app.get('category') or '(falta)'}")
    print(f"  {marca(bool(datos_app.get('icon_url')))} ícono")
    print(f"    nombre: {datos_app.get('name')}")

    faltan = []
    if datos_numero.get("status") != "CONNECTED":
        faltan.append("el número no está conectado")
    if "messages" not in campos:
        faltan.append("falta el campo messages en el webhook")
    if not datos_app.get("privacy_policy_url"):
        faltan.append("falta la URL de la política de privacidad")

    print()
    if faltan:
        print("Para publicar falta:")
        for motivo in faltan:
            print(f"  · {motivo}")
        return 1
    print("Todo listo para pasar la app a producción.")
    print("Solo queda activar el interruptor en el panel de la app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
