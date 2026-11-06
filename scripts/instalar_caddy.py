"""Instalar Caddy como servicio para publicar el bot en bot.roho.bo.

Requiere ejecutarse como administrador y que el DNS ya apunte al servidor.

Uso:
    python -m scripts.instalar_caddy            # muestra qué haría
    python -m scripts.instalar_caddy --aplicar  # instala y arranca
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HERRAMIENTAS = RAIZ / ".tools"
CADDY = HERRAMIENTAS / "caddy.exe"
DESCARGA = (
    "https://github.com/caddyserver/caddy/releases/latest/download/"
    "caddy_2.10.0_windows_amd64.zip"
)


def ejecutar(*argumentos: str) -> tuple[int, str]:
    proceso = subprocess.run(
        argumentos, capture_output=True, text=True, check=False
    )
    return proceso.returncode, (proceso.stdout + proceso.stderr).strip()


def descargar() -> None:
    HERRAMIENTAS.mkdir(exist_ok=True)
    destino = HERRAMIENTAS / "caddy.zip"
    print("descargando Caddy…")
    urllib.request.urlretrieve(DESCARGA, destino)
    shutil.unpack_archive(str(destino), str(HERRAMIENTAS))
    destino.unlink(missing_ok=True)
    if not CADDY.exists():
        raise SystemExit("No se encontró caddy.exe después de descomprimir.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    print("Objetivo: https://bot.roho.bo  →  127.0.0.1:8010")
    print(f"Caddy: {CADDY}")
    print(f"Caddyfile: {RAIZ / 'Caddyfile'}")

    if not args.aplicar:
        print("\nSimulación. Para instalar: --aplicar")
        print("Requiere: DNS apuntando al servidor y puertos 80/443 abiertos.")
        return 0

    if not CADDY.exists():
        descargar()

    codigo, salida = ejecutar(str(CADDY), "validate", "--config", "Caddyfile")
    if codigo != 0:
        print(f"El Caddyfile tiene errores:\n{salida}")
        return 1
    print("✓ Caddyfile válido")

    ejecutar(str(CADDY), "service", "stop")
    codigo, salida = ejecutar(
        str(CADDY), "service", "install", "--config", str(RAIZ / "Caddyfile")
    )
    print(salida or f"instalación: {codigo}")

    ejecutar(str(CADDY), "service", "start")
    print("\nServicio iniciado. Verificá con:")
    print("  curl.exe -I https://bot.roho.bo/health")
    print("\nNota: el certificado se emite en el primer acceso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
