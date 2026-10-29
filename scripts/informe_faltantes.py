"""Informe de faltantes: qué piden los clientes y no está en el catálogo.

Uso:
    python -m scripts.informe_faltantes
    python -m scripts.informe_faltantes --dias 7 --limite 30
    python -m scripts.informe_faltantes --csv faltantes.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

from app.db import SessionLocal
from app.services import missing


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=30)
    parser.add_argument("--limite", type=int, default=20)
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    async with SessionLocal() as session:
        datos = await missing.resumen(
            session, dias=args.dias, limite=args.limite
        )

    print(f"Faltantes de los últimos {datos['dias']} días")
    print("=" * 46)
    print(f"pedidos sin producto: {datos['total']}")
    print(f"resueltos con algo relacionado: {datos['con_respuesta']}")
    print()

    if not datos["terminos"]:
        print("Todavía no hay faltantes registrados.")
        return 0

    print(f"{'#':>2}  {'veces':>5}  {'término':<24} intención")
    print("-" * 78)
    for indice, fila in enumerate(datos["terminos"], start=1):
        print(
            f"{indice:>2}  {fila['veces']:>5}  {fila['term'][:24]:<24} "
            f"{fila['intencion'][:32]}"
        )

    if args.csv:
        ruta = Path(args.csv)
        with ruta.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(["termino", "veces", "intencion", "ultima"])
            for fila in datos["terminos"]:
                escritor.writerow(
                    [
                        fila["term"],
                        fila["veces"],
                        fila["intencion"],
                        fila["ultima"] or "",
                    ]
                )
        print(f"\ncsv: {ruta}")

    print()
    print(
        "Sugerencia: los términos con más pedidos y sin producto son los "
        "candidatos a incorporar al catálogo."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
