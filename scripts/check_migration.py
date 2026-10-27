"""Verifica que el número real quedó bien conectado.

Comprueba el número, la cuenta de WhatsApp Business, el webhook y, si se pide,
envía un mensaje de prueba. Sirve como control después de migrar.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from app.config import settings

BASE = f"https://graph.facebook.com/{settings.wa_graph_version}"


def _marca(ok: bool) -> str:
    return "OK   " if ok else "FALTA"


def resumen(estado: dict) -> list[str]:
    """Líneas del informe a partir de los datos consultados."""
    lineas = [
        f"[{_marca(estado['numero'])}] Número de teléfono "
        f"({estado.get('telefono') or 'sin configurar'})",
        f"[{_marca(estado['cuenta'])}] Cuenta de WhatsApp Business "
        f"({estado.get('cuenta') or 'sin configurar'})",
        f"[{_marca(estado['webhook'])}] Webhook suscripto",
        f"[{_marca(estado['token'])}] Token válido",
    ]
    if estado.get("nombre"):
        lineas.append(f"       Nombre visible: {estado['nombre']}")
    if estado.get("calidad"):
        lineas.append(f"       Calidad del número: {estado['calidad']}")
    if estado.get("limite"):
        lineas.append(f"       Límite de mensajería: {estado['limite']}")
    if estado.get("webhook_url"):
        lineas.append(f"       Webhook: {estado['webhook_url']}")
    return lineas


async def consultar() -> dict:
    estado = {
        "numero": bool(settings.wa_phone_number_id),
        "cuenta": bool(settings.wa_waba_id),
        "webhook": False,
        "token": False,
        "telefono": settings.wa_business_number,
        "cuenta_id": settings.wa_waba_id,
    }
    if not settings.wa_access_token:
        return estado
    async with httpx.AsyncClient(timeout=20) as cliente:
        # Número
        if settings.wa_phone_number_id:
            try:
                r = await cliente.get(
                    f"{BASE}/{settings.wa_phone_number_id}",
                    params={
                        "fields": (
                            "display_phone_number,verified_name,"
                            "quality_rating,status"
                        ),
                        "access_token": settings.wa_access_token,
                    },
                )
                if r.status_code == 200:
                    datos = r.json()
                    estado["token"] = True
                    estado["numero"] = True
                    estado["nombre"] = datos.get("verified_name")
                    estado["telefono"] = datos.get(
                        "display_phone_number", settings.wa_business_number
                    )
                    estado["calidad"] = datos.get("quality_rating")
            except httpx.HTTPError:
                pass
        # Cuenta + webhook
        if settings.wa_waba_id:
            try:
                r = await cliente.get(
                    f"{BASE}/{settings.wa_waba_id}/subscribed_apps",
                    params={"access_token": settings.wa_access_token},
                )
                if r.status_code == 200:
                    apps = r.json().get("data") or []
                    estado["cuenta"] = True
                    estado["webhook"] = bool(apps)
                    if apps:
                        estado["webhook_url"] = (
                            apps[0].get("override_callback_uri") or ""
                        )
            except httpx.HTTPError:
                pass
    return estado


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", type=str, default="")
    args = parser.parse_args()

    estado = await consultar()
    print("Verificación de la migración")
    print("=" * 40)
    for linea in resumen(estado):
        print(linea)

    if args.to:
        from app.whatsapp import WhatsAppClient

        cliente = WhatsAppClient()
        try:
            mid = await cliente.send_text(
                args.to,
                "Prueba de conexión de ROHO Homecenter. Si recibís este "
                "mensaje, el número quedó bien configurado.",
            )
            print(f"\nMensaje de prueba enviado: {mid}")
        except Exception as exc:  # noqa: BLE001
            print(f"\nNo se pudo enviar la prueba: {str(exc)[:300]}")
        finally:
            await cliente.close()

    faltan = [clave for clave in ("numero", "cuenta", "webhook", "token") if not estado[clave]]
    if faltan:
        print(f"\nFalta: {', '.join(faltan)}")
        return 1
    print("\nTodo listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
