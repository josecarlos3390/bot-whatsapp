"""Datos que faltan para recomendar bien.

Para un aire hace falta saber los metros; para una heladera, cuántas personas;
para una tele, la distancia. Si el cliente no lo dijo, se pregunta antes de
listar, con opciones cortas.
"""

from __future__ import annotations

import re

# Rubro -> (pregunta, clave, opciones)
GUIA: dict[str, dict] = {
    "aire acondicionado": {
        "clave": "m2",
        "pregunta": "¿Cuántos metros cuadrados tiene el ambiente?",
        "opciones": [
            ("Hasta 12 m²", "9000 BTU"),
            ("13 a 18 m²", "12000 BTU"),
            ("19 a 25 m²", "18000 BTU"),
            ("26 a 35 m²", "24000 BTU"),
        ],
        "termino": "aire acondicionado",
    },
    "heladera": {
        "clave": "personas",
        "pregunta": "¿Cuántas personas viven en la casa?",
        "opciones": [
            ("1 a 2", "200 litros"),
            ("3 a 4", "300 litros"),
            ("5 o más", "400 litros"),
        ],
        "termino": "heladera",
    },
    "lavadora": {
        "clave": "personas",
        "pregunta": "¿Cuántas personas lavan ropa en la casa?",
        "opciones": [
            ("1 a 2", "8 kg"),
            ("3 a 4", "12 kg"),
            ("5 o más", "16 kg"),
        ],
        "termino": "lavadora",
    },
    "televisor": {
        "clave": "distancia",
        "pregunta": "¿A qué distancia vas a mirar la tele?",
        "opciones": [
            ("Hasta 2 m", "43 pulgadas"),
            ("2 a 2,5 m", "50 pulgadas"),
            ("2,5 a 3 m", "55 pulgadas"),
            ("Más de 3 m", "65 pulgadas"),
        ],
        "termino": "televisor",
    },
    "pintura": {
        "clave": "m2",
        "pregunta": "¿Cuántos metros cuadrados de pared vas a pintar?",
        "opciones": [
            ("Hasta 20 m²", "4 litros"),
            ("20 a 40 m²", "10 litros"),
            ("40 a 80 m²", "20 litros"),
        ],
        "termino": "pintura",
    },
    "colchon": {
        "clave": "plazas",
        "pregunta": "¿El colchón es para una o dos personas?",
        "opciones": [
            ("1 persona", "1 plaza"),
            ("1,5 plazas", "1.5 plazas"),
            ("2 personas", "2 plazas"),
        ],
        "termino": "colchon",
    },
    "ventilador": {
        "clave": "m2",
        "pregunta": "¿Cuántos metros cuadrados tiene el ambiente?",
        "opciones": [
            ("Hasta 12 m²", "16 pulgadas"),
            ("13 a 20 m²", "18 pulgadas"),
            ("Más de 20 m²", "20 pulgadas"),
        ],
        "termino": "ventilador",
    },
    "cortina": {
        "clave": "ancho",
        "pregunta": "¿Cuánto mide de ancho la ventana?",
        "opciones": [
            ("Hasta 1,5 m", "cortina 150"),
            ("1,5 a 2 m", "cortina 200"),
            ("Más de 2 m", "cortina 250"),
        ],
        "termino": "cortina",
    },
}

# El cliente ya eligió un tamaño: no se pregunta otra cosa.
_TAMANO = re.compile(
    r"\b(\d{1,2}\s*(pulgadas|pulg|\"))"
    r"|(\d{2,4}\s*(litros|lt))"
    r"|(\d{1,2}\s*(kg|kilos))"
    r"|(\d{4,5}\s*btu)"
    r"|(\d\s*(plazas?|cm|mm))\b",
    re.IGNORECASE,
)

# Palabras del cliente que indican que ya dio el dato.
_YA_DIJO = {
    "m2": re.compile(r"\b\d{1,3}\s*(m2|m²|metros|mt2)\b", re.IGNORECASE),
    "personas": re.compile(r"\b(una|dos|tres|cuatro|cinco|\d)\s*(persona|personas|somos)\b|\bsomos\s+\w+", re.IGNORECASE),
    "distancia": re.compile(r"\b\d(,5)?\s*(m|metros|mt)\b", re.IGNORECASE),
    "plazas": re.compile(
        r"\b(una|dos|1|2|1,5)\s*(plaza|plazas|plasa|plasas|persona|personas)\b",
        re.IGNORECASE,
    ),
    "ancho": re.compile(r"\b\d(,\d)?\s*(m|metros|cm)\b", re.IGNORECASE),
}


def rubro(texto: str) -> str:
    """Rubro de la guía que corresponde al texto, si hay."""
    valor = (texto or "").lower()
    # "freidora de aire" o "purificador de aire" no son aires acondicionados.
    if re.search(
        r"\b(freidora|purificador|humidificador|calentador)\s+de\s+aire\b",
        valor,
    ):
        return ""
    if re.search(
        r"\baire\s+(acondicionado|split)\b|\bacondicionado\b|\bsplit\b|\binverter\b",
        valor,
    ):
        return "aire acondicionado"
    if re.search(r"\b(helader|refriger|nevera)\w*", valor):
        return "heladera"
    if re.search(r"\b(lavadora|lavarropas)\w*", valor):
        return "lavadora"
    if re.search(r"\b(tv|tele|televisor)\w*", valor):
        return "televisor"
    if re.search(r"\bpintur\w*", valor):
        return "pintura"
    if re.search(r"\bcolch\w*", valor):
        return "colchon"
    if re.search(r"\bventilador\w*", valor):
        return "ventilador"
    if re.search(r"\bcortina\w*", valor):
        return "cortina"
    return ""


def falta_dato(texto: str, rubro_detectado: str = "") -> dict | None:
    """¿Falta el dato clave para recomendar este rubro?"""
    elegido = rubro_detectado or rubro(texto)
    if not elegido or elegido not in GUIA:
        return None
    datos = GUIA[elegido]
    # Si ya eligió tamaño (50 pulgadas, 300 litros, 12 kg), no hace falta
    # preguntar la distancia ni las personas.
    if _TAMANO.search(texto or ""):
        return None
    patron = _YA_DIJO.get(datos["clave"])
    if patron and patron.search(texto or ""):
        return None  # el cliente ya lo dijo
    return {"rubro": elegido, **datos}


def opciones_botones(entrada: dict) -> list[dict]:
    """Botones con la búsqueda que corresponde a cada rango."""
    salida = []
    for etiqueta, medida in entrada["opciones"][:3]:
        consulta = f"{entrada['termino']} {medida}"
        salida.append({"id": f"uso:{consulta}", "title": etiqueta[:20]})
    return salida


def explicar(rubro_detectado: str, medida: str, precio: str = "") -> str:
    """Frase que justifica la recomendación con el criterio de la guía."""
    texto = f"Para {medida}, eso es lo que necesitás"
    if precio:
        texto += f" y arranca en {precio}"
    return texto + "."
