"""Puntajes del fuzzing: promedio, criterios y comparación mensual."""

from __future__ import annotations

CRITERIOS = (
    "responde",
    "no_inventa",
    "no_repite",
    "siguiente_paso",
    "tono",
)


def promedio(resultados: list[dict]) -> float:
    notas = [
        float(item["nota"])
        for item in resultados
        if isinstance(item.get("nota"), (int, float))
    ]
    if not notas:
        return 0.0
    return round(sum(notas) / len(notas), 2)


def por_criterio(resultados: list[dict]) -> dict[str, float]:
    """Promedio de cada criterio del juez (0 a 2)."""
    totales: dict[str, list[float]] = {clave: [] for clave in CRITERIOS}
    for item in resultados:
        criterios = item.get("criterios")
        if not isinstance(criterios, dict):
            continue
        for clave in CRITERIOS:
            valor = criterios.get(clave)
            if isinstance(valor, (int, float)):
                totales[clave].append(float(valor))
    return {
        clave: round(sum(valores) / len(valores), 2)
        for clave, valores in totales.items()
        if valores
    }


def comparar(anterior: dict | None, actual: dict) -> list[str]:
    """Líneas de comparación entre dos corridas."""
    if not anterior:
        return ["Sin corrida anterior: esta es la línea base."]
    lineas = []
    antes = float(anterior.get("promedio") or 0)
    ahora = float(actual.get("promedio") or 0)
    diferencia = round(ahora - antes, 2)
    signo = "+" if diferencia >= 0 else ""
    lineas.append(
        f"Promedio: {antes} → {ahora} ({signo}{diferencia})"
    )
    previos = anterior.get("criterios") or {}
    actuales = actual.get("criterios") or {}
    for clave, valor in actuales.items():
        previo = previos.get(clave)
        if previo is None:
            continue
        delta = round(float(valor) - float(previo), 2)
        if abs(delta) >= 0.1:
            signo = "+" if delta >= 0 else ""
            lineas.append(f"  {clave}: {previo} → {valor} ({signo}{delta})")
    return lineas


def _mediana(valores: list[float]) -> float:
    import statistics

    if not valores:
        return 0.0
    return round(float(statistics.median(valores)), 2)


def agregar(resultados: list[dict]) -> dict:
    """Agrupa por escenario y usa la mediana de las repeticiones.

    Una sola pasada varía demasiado: con tres repeticiones y mediana, una
    conversación rara no mueve el número.
    """
    grupos: dict[str, list[dict]] = {}
    for item in resultados:
        clave = str(item.get("escenario") or "libre")
        grupos.setdefault(clave, []).append(item)

    por_escenario: dict[str, dict] = {}
    notas: list[float] = []
    criterios: dict[str, list[float]] = {clave: [] for clave in CRITERIOS}
    for clave, items in grupos.items():
        nota = _mediana(
            [float(i["nota"]) for i in items if isinstance(i.get("nota"), (int, float))]
        )
        por_escenario[clave] = {"nota": nota, "repeticiones": len(items)}
        if nota:
            notas.append(nota)
        promedios = por_criterio(items)
        for nombre, valor in promedios.items():
            criterios[nombre].append(float(valor))

    return {
        "promedio": round(sum(notas) / len(notas), 2) if notas else 0.0,
        "criterios": {
            nombre: _mediana(valores)
            for nombre, valores in criterios.items()
            if valores
        },
        "por_escenario": por_escenario,
        "escenarios_evaluados": len(grupos),
    }
