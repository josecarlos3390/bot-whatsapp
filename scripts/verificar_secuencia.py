"""Verifica el cambio del PaaS: documento/email sí, secuencia no.

Se corre después del deploy. Comprueba tres cosas:

1. La búsqueda por documento sigue devolviendo pedidos.
2. Un número de secuencia **ya no** devuelve pedidos por la ruta de cliente
   (antes devolvía un pedido ajeno).
3. La ruta explícita de secuencia responde.

Uso:
    python -m scripts.verificar_secuencia
    python -m scripts.verificar_secuencia --documento 5403339 --secuencia 500195
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from app.config import settings


def evaluar(
    documento: list[dict],
    secuencia_por_cliente: list[dict],
    secuencia_explicita: dict | None,
) -> tuple[bool, list[str]]:
    """Decide si el cambio quedó bien aplicado."""
    lineas: list[str] = []
    ok = True

    if documento:
        lineas.append(f"OK   documento devuelve {len(documento)} pedido(s)")
    else:
        lineas.append("FALLA documento no devuelve pedidos")
        ok = False

    if secuencia_por_cliente:
        lineas.append(
            "FALLA la secuencia todavía devuelve pedidos por la ruta de "
            f"cliente ({len(secuencia_por_cliente)})"
        )
        ok = False
    else:
        lineas.append("OK   la secuencia ya no resuelve por la ruta de cliente")

    if secuencia_explicita:
        lineas.append("OK   /orders/by-sequence responde")
    else:
        lineas.append("FALLA /orders/by-sequence no responde")
        ok = False
    return ok, lineas


async def consultar(documento: str, secuencia: str) -> tuple[bool, list[str]]:
    base = settings.sap_paas_url.rstrip("/")
    headers = {"X-Api-Key": settings.sap_paas_api_key}
    async with httpx.AsyncClient(timeout=25) as cliente:
        por_documento = await cliente.get(
            f"{base}/api/vtex/customers/{documento}/purchases",
            params={"top": 5},
            headers=headers,
        )
        por_secuencia_cliente = await cliente.get(
            f"{base}/api/vtex/customers/{secuencia}/purchases",
            params={"top": 5},
            headers=headers,
        )
        explicita = await cliente.get(
            f"{base}/api/vtex/orders/by-sequence/{secuencia}",
            headers=headers,
        )

    def lista(respuesta) -> list[dict]:
        if respuesta.status_code != 200:
            return []
        datos = respuesta.json()
        if isinstance(datos, dict):
            valor = datos.get("value")
            return valor if isinstance(valor, list) else []
        return datos if isinstance(datos, list) else []

    return evaluar(
        lista(por_documento),
        lista(por_secuencia_cliente),
        explicita.json() if explicita.status_code == 200 else None,
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documento", default="5403339")
    parser.add_argument("--secuencia", default="500195")
    args = parser.parse_args()

    print("Verificación del cambio del PaaS (rutas de VTEX)")
    print("=" * 40)
    ok, lineas = await consultar(args.documento, args.secuencia)
    for linea in lineas:
        print(linea)
    print()
    if ok:
        print("Listo: se puede activar ORDER_SEQUENCE_LOOKUP_ENABLED=true")
        return 0
    print("Todavía no: revisar antes de activar la bandera")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
