"""Cambiar el número de WhatsApp del bot sin editar el .env a mano.

Deja respaldo del .env anterior y solo toca las claves de WhatsApp.

Uso:
    python -m scripts.cambiar_numero_whatsapp `
        --numero-id 123456789 `
        --waba 987654321 `
        --telefono +59169114625 `
        --token EAAG... `
        --dominio https://bot.roho.com.bo `
        --aplicar

Sin --aplicar solo muestra qué cambiaría.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ENV = Path(".env")

CLAVES = {
    "numero_id": "WA_PHONE_NUMBER_ID",
    "waba": "WA_WABA_ID",
    "telefono": "WA_BUSINESS_NUMBER",
    "token": "WA_ACCESS_TOKEN",
    "dominio": "PUBLIC_BASE_URL",
}


def leer_lineas() -> list[str]:
    if not ENV.exists():
        raise SystemExit("No existe .env en el directorio actual.")
    return ENV.read_text(encoding="utf-8").splitlines()


def valor_actual(lineas: list[str], clave: str) -> str:
    for linea in lineas:
        if linea.startswith(f"{clave}="):
            return linea.split("=", 1)[1]
    return ""


def aplicar(lineas: list[str], clave: str, valor: str) -> list[str]:
    """Reemplaza la clave o la agrega al final."""
    salida: list[str] = []
    reemplazada = False
    for linea in lineas:
        if linea.startswith(f"{clave}="):
            salida.append(f"{clave}={valor}")
            reemplazada = True
        else:
            salida.append(linea)
    if not reemplazada:
        salida.append(f"{clave}={valor}")
    return salida


def ocultar(valor: str) -> str:
    if not valor:
        return "(vacío)"
    if len(valor) <= 12:
        return valor[:4] + "…"
    return f"{valor[:6]}…{valor[-4:]} ({len(valor)} caracteres)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--numero-id", default="")
    parser.add_argument("--waba", default="")
    parser.add_argument("--telefono", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--dominio", default="")
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()

    cambios = {
        clave: getattr(args, destino)
        for destino, clave in CLAVES.items()
        if getattr(args, destino)
    }
    if not cambios:
        parser.error("No pasaste ningún valor para cambiar.")

    if "WA_ACCESS_TOKEN" in cambios and len(cambios["WA_ACCESS_TOKEN"]) < 100:
        print(
            "⚠️  El token parece corto. Los del usuario del sistema tienen "
            "unos 200 caracteres."
        )

    lineas = leer_lineas()
    print("Cambios")
    for clave, valor in cambios.items():
        actual = valor_actual(lineas, clave)
        mostrado = ocultar(valor) if clave == "WA_ACCESS_TOKEN" else valor
        previo = (
            ocultar(actual) if clave == "WA_ACCESS_TOKEN" else (actual or "(vacío)")
        )
        print(f"  · {clave:<22} {previo}  →  {mostrado}")

    if not args.aplicar:
        print("\nSimulación: no se escribió nada. Para aplicar: --aplicar")
        return 0

    # Los respaldos llevan secretos: van a .tools (ignorado por git).
    carpeta = Path(".tools") / "env-bak"
    carpeta.mkdir(parents=True, exist_ok=True)
    respaldo = carpeta / f".env.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(ENV, respaldo)

    for clave, valor in cambios.items():
        lineas = aplicar(lineas, clave, valor)
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"\n✓ .env actualizado. Respaldo: {respaldo.name}")
    print("Reiniciá el servicio y verificá con:")
    print("  .\\.venv\\Scripts\\python.exe -m scripts.verificar_numero")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
