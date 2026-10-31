"""Una pregunta antes de listar: cómo atiende un vendedor.

Elegir «Iluminación» y recibir ocho productos sin más no es atender: el
vendedor pregunta dónde va, para qué es, cuánto quiere gastar. Acá están esas
preguntas por rubro, con opciones cortas que llevan a la búsqueda correcta.
"""

from __future__ import annotations

# clave de categoría -> pregunta y opciones (etiqueta, término de búsqueda)
PREGUNTAS: dict[str, dict] = {
    "iluminacion": {
        "texto": "¿Dónde la vas a poner?",
        "opciones": [
            ("Interior", "lampara interior"),
            ("Exterior", "lampara exterior"),
            ("Focos y tubos", "foco"),
        ],
    },
    "sala": {
        "texto": "¿Qué estás buscando para la sala?",
        "opciones": [
            ("Sofá", "sofa"),
            ("Mesa", "mesa"),
            ("Rack para TV", "rack"),
        ],
    },
    "dormitorio": {
        "texto": "¿Qué necesitás para el dormitorio?",
        "opciones": [
            ("Colchón", "colchon"),
            ("Base o somier", "base"),
            ("Ropero", "ropero"),
        ],
    },
    "bano": {
        "texto": "¿Qué necesitás para el baño?",
        "opciones": [
            ("Grifería", "griferia"),
            ("Ducha", "ducha"),
            ("Accesorios", "accesorio bano"),
        ],
    },
    "cocina": {
        "texto": "¿Qué buscás para la cocina?",
        "opciones": [
            ("Cocina", "cocina"),
            ("Campana", "campana"),
            ("Mesada o pileta", "mesada"),
        ],
    },
    "electrodomesticos": {
        "texto": "¿Qué electrodoméstico necesitás?",
        "opciones": [
            ("Heladera", "heladera"),
            ("Lavadora", "lavadora"),
            ("Microondas", "microondas"),
        ],
    },
    "herramientas": {
        "texto": "¿Qué tipo de herramienta?",
        "opciones": [
            ("Eléctrica", "taladro"),
            ("Manual", "llave"),
            ("Jardín", "jardin"),
        ],
    },
}

SIN_PREGUNTA = {"ofertas", "novedades", "todos"}


def pregunta(key: str) -> dict | None:
    """Pregunta guía de la categoría, si tiene."""
    if not key or key.lower() in SIN_PREGUNTA:
        return None
    return PREGUNTAS.get(key.lower())


def opciones(key: str, utiles: list | None = None) -> list[dict]:
    """Opciones de la pregunta, más «ver todo».

    Va como lista (no botones): WhatsApp permite 3 botones y acá hay 4.
    """
    datos = PREGUNTAS[key.lower()]
    elegidas = utiles if utiles is not None else datos["opciones"][:3]
    salida = [
        {
            "id": f"sub:{key}|{termino}",
            "title": etiqueta[:24],
            "description": termino,
        }
        for etiqueta, termino in elegidas[:3]
    ]
    salida.append(
        {
            "id": f"sub:{key}|todo",
            "title": "Ver todo",
            "description": "Mostrame todas las opciones",
        }
    )
    return salida
