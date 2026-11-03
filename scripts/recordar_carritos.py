"""Recordar los carritos que quedaron sin terminar.

Por defecto no envía nada: muestra qué mandaría. Para enviar de verdad hay
que pasar ``--enviar`` y tener el recordatorio activado en la configuración.

Uso:
    python -m scripts.recordar_carritos
    python -m scripts.recordar_carritos --enviar
    python -m scripts.recordar_carritos --horas 6
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import settings
from app.db import SessionLocal
from app.services import carrito_abandonado


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horas", type=int, default=settings.cart_reminder_hours)
    parser.add_argument("--limite", type=int, default=20)
    parser.add_argument("--enviar", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import Contact

    async with SessionLocal() as session:
        pendientes = await carrito_abandonado.pendientes(
            session, horas=args.horas, limite=args.limite
        )
        if not pendientes:
            print(f"Sin carritos quietos hace {args.horas} h.")
            return 0

        print(f"Carritos para recordar: {len(pendientes)}\n")
        enviados = 0
        for carrito, contacto, items in pendientes:
            filas = await carrito_abandonado.enriquecer(session, items)
            total = sum(
                (fila["unit_price"] * fila["quantity"] for fila in filas),
                start=type(filas[0]["unit_price"])(0) if filas else 0,
            )
            abierta = await carrito_abandonado.ventana_abierta(
                session, contacto
            )
            canal = "texto libre"
            if not abierta:
                canal = (
                    f"plantilla {settings.cart_template_name}"
                    if settings.cart_template_name
                    else "NO SE PUEDE (ventana cerrada, sin plantilla)"
                )
            print(
                f"· {contacto.name or contacto.wa_id} ({contacto.wa_id}) · "
                f"{len(filas)} artículo(s) · total {total} · {canal}"
            )
            print(
                carrito_abandonado.texto_con_nombres(contacto, filas, total)
                .replace("\n", "\n    ")
            )
            print()
            if not args.enviar:
                continue
            try:
                resultado = await carrito_abandonado.recordar(
                    session, carrito, contacto, items
                )
            except Exception as exc:  # noqa: BLE001 - se informa y sigue
                print(f"   ✗ error: {str(exc)[:120]}")
                continue
            if resultado.get("ok"):
                enviados += 1
                print(f"   ✓ enviado por {resultado.get('canal')}")
            else:
                print(f"   ✗ no enviado: {resultado.get('motivo')}")

        if not args.enviar:
            print("Simulación: no se envió nada. Para enviar: --enviar")
        else:
            print(f"enviados: {enviados} de {len(pendientes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
