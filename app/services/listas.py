"""Ordenar y numerar los listados de productos con precio.

El modelo a veces devuelve opciones desordenadas o con la numeración repetida:

```
1. TV Tokyo — Bs 1.597
2. TV Houce — Bs 1.499
```

Para el cliente, un listado de precios tiene que ir de menor a mayor y con un
correlativo limpio. Esto se aplica sobre el texto final, sin importar quién lo
haya escrito.
"""

from __future__ import annotations

import re

# Línea de listado: "1. Producto — Bs 1.499", "2) Producto Bs 1.499,00"
_LINEA = re.compile(
    r"^\s*(?P<numero>\d{1,2})\s*[.)\-–]\s*(?P<texto>.+?)\s*$"
)
_PRECIO = re.compile(
    r"(?:bs\.?|bob|\$)\s*(?P<monto>\d[\d.,]*)",
    re.IGNORECASE,
)


def a_numero(monto: str) -> float | None:
    """Convierte '1.499,00', '1,499.00' o '1499' a número."""
    crudo = (monto or "").strip().replace(" ", "")
    if not crudo:
        return None
    tiene_coma = "," in crudo
    tiene_punto = "." in crudo
    if tiene_coma and tiene_punto:
        # El separador que aparece último es el decimal.
        if crudo.rfind(",") > crudo.rfind("."):
            crudo = crudo.replace(".", "").replace(",", ".")
        else:
            crudo = crudo.replace(",", "")
    elif tiene_coma:
        partes = crudo.split(",")
        if len(partes[-1]) == 3 and len(partes) > 1:
            crudo = crudo.replace(",", "")
        else:
            crudo = crudo.replace(",", ".")
    elif tiene_punto:
        partes = crudo.split(".")
        if len(partes[-1]) == 3 and len(partes) > 1:
            crudo = crudo.replace(".", "")
    try:
        return float(crudo)
    except ValueError:
        return None


def _precio_de(texto: str) -> float | None:
    encontrado = _PRECIO.search(texto or "")
    if encontrado is None:
        return None
    return a_numero(encontrado.group("monto"))


def normalizar(texto: str) -> str:
    """Ordena por precio y renumera los bloques de líneas numeradas."""
    lineas = (texto or "").split("\n")
    salida: list[str] = []
    bloque: list[tuple[str, float]] = []
    numeros: list[str] = []

    def cerrar() -> None:
        """Vuelca el bloque: ordenado si todas las líneas tienen precio."""
        if not bloque:
            return
        con_precio = [item for item in bloque if item[1] is not None]
        if len(bloque) >= 2 and len(con_precio) == len(bloque):
            bloque.sort(key=lambda par: par[1] or 0)
        for indice, (contenido, _valor) in enumerate(bloque, start=1):
            salida.append(f"{indice}. {contenido}")
        bloque.clear()
        numeros.clear()

    for linea in lineas:
        coincidencia = _LINEA.match(linea)
        if coincidencia is None:
            cerrar()
            salida.append(linea)
            continue
        contenido = coincidencia.group("texto")
        bloque.append((contenido, _precio_de(contenido)))
        numeros.append(coincidencia.group("numero"))
    cerrar()
    return "\n".join(salida)


def tiene_listado(texto: str) -> bool:
    """¿Hay al menos dos líneas numeradas con precio?"""
    con_precio = 0
    for linea in (texto or "").split("\n"):
        coincidencia = _LINEA.match(linea)
        if coincidencia and _precio_de(coincidencia.group("texto")) is not None:
            con_precio += 1
            if con_precio >= 2:
                return True
    return False
