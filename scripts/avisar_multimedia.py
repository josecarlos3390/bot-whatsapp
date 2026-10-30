"""Segundo aviso: el bot entiende texto, audio e imágenes.

Uso:
    python -m scripts.avisar_multimedia
"""

from __future__ import annotations

import asyncio

from app.whatsapp import WhatsAppClient

NUMEROS = [
    "59177810716",
    "59169006969",
    "59179050453",
    "59176012480",
]

MENSAJE = (
    "Ah, y algo importante 👀\n\n"
    "No hace falta que me escribas: también *entiendo audios* 🎤 y "
    "*fotos* 📷.\n\n"
    "Probá mandarme un audio contándome qué buscás, o una foto del producto "
    "que tenés en mente (una licuadora, un mueble, lo que sea) y te digo qué "
    "tengo parecido.\n\n"
    "Y si me contás para qué lo necesitás, te acierto mucho mejor 💡\n\n"
    "Cuando quieras 👇"
)


async def main() -> int:
    cliente = WhatsAppClient()
    enviados = 0
    fallidos = 0
    try:
        for destino in NUMEROS:
            try:
                await cliente.send_text(destino, MENSAJE)
                enviados += 1
                print(f"enviado a {destino}")
            except Exception as exc:  # noqa: BLE001
                fallidos += 1
                print(f"FALLÓ {destino}: {str(exc)[:110]}")
            await asyncio.sleep(2)
    finally:
        await cliente.close()
    print(f"\nenviados: {enviados} | fallidos: {fallidos}")
    return 0 if not fallidos else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
