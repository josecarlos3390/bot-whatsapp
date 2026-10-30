"""Informe de consumo de la IA: tokens y costo estimado.

Uso:
    python -m scripts.informe_consumo
    python -m scripts.informe_consumo --dias 30
"""

from __future__ import annotations

import argparse
import asyncio

from app.services import ai_usage


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=7)
    args = parser.parse_args()

    datos = ai_usage.resumen(dias=args.dias)
    print(f"Consumo de IA · últimos {datos['dias']} días")
    print("=" * 52)
    print(f"llamadas: {datos['llamadas']}")
    print(f"tokens:   {datos['prompt']:,} entrada + {datos['completion']:,} salida")
    print(f"costo:    US$ {datos['costo_usd']:.4f} (estimado)")

    if datos["operaciones"]:
        print("\npor tipo de uso:")
        print(f"{'operación':<16}{'llamadas':>9}{'tokens':>12}{'costo':>10}")
        print("-" * 47)
        for nombre, fila in datos["operaciones"].items():
            tokens = fila["prompt"] + fila["completion"]
            print(
                f"{nombre:<16}{fila['llamadas']:>9}{tokens:>12,}"
                f"{'US$ ' + format(fila['costo'], '.3f'):>10}"
            )

    if datos["dias_detalle"]:
        print("\npor día:")
        for dia, fila in datos["dias_detalle"].items():
            print(
                f"  {dia}  {fila['llamadas']:>4} llamadas"
                f"  US$ {fila['costo']:.3f}"
            )

    if datos["llamadas"]:
        print(
            f"\npromedio por llamada: "
            f"{round((datos['prompt'] + datos['completion']) / datos['llamadas']):,} "
            "tokens"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
