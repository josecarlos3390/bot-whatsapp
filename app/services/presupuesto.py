"""Presupuesto: la pregunta que más filtra y la que más vende.

Un vendedor no muestra un sofá de Bs 9.000 a quien pidió algo económico. Si el
cliente no dijo cuánto quiere gastar, se pregunta con rangos reales sacados
del catálogo (no inventados).
"""

from __future__ import annotations

import re

# Palabras que piden lo barato.
BARATO = re.compile(
    r"\b(econ[oó]mic\w*|barat\w*|lo m[aá]s barato|ajustad\w*|"
    r"no quiero gastar|poco presupuesto|sin gastar mucho)\b",
    re.IGNORECASE,
)

# "hasta 1500", "máximo 800", "menos de 2.000"
LIMITE = re.compile(
    r"\b(?:hasta|m[aá]ximo|menos de|no m[aá]s de|tope)\s*"
    r"(?:bs\.?|bob)?\s*([\d\.][\d\.\,]*)\b",
    re.IGNORECASE,
)


def _numero(texto: str) -> float:
    limpio = (
        texto.replace(".", "").replace(",", ".").strip()
    )
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def limite(texto: str) -> float | None:
    """Monto máximo que dijo el cliente, si lo dijo."""
    encontrado = LIMITE.search(texto or "")
    if not encontrado:
        return None
    valor = _numero(encontrado.group(1))
    return valor if valor > 0 else None


def quiere_barato(texto: str) -> bool:
    return bool(BARATO.search(texto or ""))


def bandas(precios: list[float]) -> list[dict]:
    """Tres rangos con precios reales del catálogo."""
    validos = sorted(precio for precio in precios if precio > 0)
    if len(validos) < 4:
        return []
    minimo = validos[0]
    maximo = validos[-1]
    # Si no hay diferencia, preguntar molesta.
    if minimo <= 0 or maximo / minimo < 2.2:
        return []
    corte1 = validos[len(validos) // 3]
    corte2 = validos[(len(validos) * 2) // 3]
    if corte1 <= minimo:
        corte1 = round((minimo + maximo) / 3, -1)
    if corte2 <= corte1:
        corte2 = round((minimo + maximo) * 2 / 3, -1)

    def _fmt(valor: float) -> str:
        return f"{valor:,.0f}".replace(",", ".")

    return [
        {"label": f"Hasta Bs {_fmt(corte1)}", "max": corte1},
        {"label": f"Hasta Bs {_fmt(corte2)}", "max": corte2},
        {"label": "Sin límite", "max": 0},
    ]


def botones(categoria: str, rangos: list[dict]) -> list[dict]:
    """Botones para elegir el presupuesto."""
    salida = []
    for rango in rangos[:2]:
        salida.append(
            {
                "id": f"price:{categoria}|{int(rango['max'])}",
                "title": rango["label"][:20],
            }
        )
    salida.append({"id": f"price:{categoria}|0", "title": "Sin límite"})
    return salida


def texto() -> str:
    return (
        "¿Hasta cuánto querés gastar?\n"
        "Así te muestro opciones que entren en tu presupuesto."
    )
