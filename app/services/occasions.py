"""Mapa curado de ocasiones y relaciones con el catálogo.

El archivo `knowledge/occasions.json` es la fuente aprobada. El script
`scripts/generate_occasions.py` solo genera borradores para revisión.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PATH = Path(__file__).resolve().parent.parent.parent / "knowledge" / "occasions.json"

FALLBACK = {
    "halloween": {
        "label": "Halloween",
        "aliases": ["halloween", "halloweén"],
        "direct": [
            "disfraz",
            "dulce",
            "caramelo",
            "calabaza",
            "vela",
            "decoracion",
            "maquillaje",
        ],
        "exclude": [
            "papa noel",
            "navidad",
            "santa",
            "silla",
            "sillon",
            "mueble",
            "mesa",
            "cama",
            "colchon",
            "pintura",
            "madera",
            "tapa",
        ],
        "exclude_categories": [
            "MUEBLES",
            "MADERA Y TABLEROS",
            "PINTURA",
            "FERRETERIA",
            "ELECTRICIDAD",
        ],
        "bridges": [
            {"label": "una noche de película", "terms": ["televisor", "tv"]},
            {"label": "decoración para la noche", "terms": ["portavela", "vela"]},
        ],
    },
    "navidad": {
        "label": "Navidad",
        "aliases": ["navidad", "navideño", "navideña"],
        "direct": [
            "navidad",
            "adorno navideno",
            "arbol navideno",
            "pesebre",
            "disfraz",
            "vela",
        ],
        "exclude": ["halloween"],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [
            {"label": "una mesa especial", "terms": ["mantel", "vajilla"]},
        ],
    },
    "dia_de_la_madre": {
        "label": "Día de la Madre",
        "aliases": ["día de la madre", "dia de la madre"],
        "direct": ["florero", "vela", "perfume", "caja de regalo", "cubrecama"],
        "exclude": [],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "decoración", "terms": ["decoracion", "florero"]}],
    },
    "san_valentin": {
        "label": "San Valentín",
        "aliases": ["san valentín", "san valentin", "día del amor", "dia del amor"],
        "direct": ["vela", "florero", "caja de regalo", "cubrecama"],
        "exclude": [],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "una cena especial", "terms": ["vajilla", "mantel"]}],
    },
    "cumpleanos": {
        "label": "cumpleaños",
        "aliases": ["cumpleaños", "cumpleanos", "fiesta de cumpleaños"],
        "direct": ["vela", "globos", "mantel", "vajilla"],
        "exclude": [],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "una mesa especial", "terms": ["mantel", "vajilla"]}],
    },
    "dia_del_padre": {
        "label": "Día del Padre",
        "aliases": ["día del padre", "dia del padre"],
        "direct": ["herramienta", "parrilla", "set de herramientas", "reloj"],
        "exclude": ["navidad", "halloween"],
        "exclude_categories": ["MUEBLES"],
        "bridges": [{"label": "para el hogar", "terms": ["herramienta", "iluminacion"]}],
    },
    "dia_del_nino": {
        "label": "Día del Niño",
        "aliases": ["día del niño", "dia del nino"],
        "direct": ["juguete", "peluche", "bicicleta", "dulce"],
        "exclude": [],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "para jugar", "terms": ["juguete", "peluche"]}],
    },
    "ano_nuevo": {
        "label": "Año Nuevo",
        "aliases": ["año nuevo", "ano nuevo", "fin de año", "fin de ano"],
        "direct": ["vela", "copa", "mantel", "adorno"],
        "exclude": ["halloween"],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "una mesa especial", "terms": ["vajilla", "mantel"]}],
    },
    "mudanza": {
        "label": "mudanza",
        "aliases": ["mudanza", "mudarme", "casa nueva", "departamento nuevo"],
        "direct": ["organizador", "caja", "cortina", "lampara", "almohada"],
        "exclude": ["navidad", "halloween"],
        "exclude_categories": ["AUTOMOTRIZ"],
        "bridges": [{"label": "para ordenar", "terms": ["organizador", "caja"]}],
    },
    "bebe": {
        "label": "bebé",
        "aliases": ["bebé", "bebe", "baby shower", "recién nacido", "recien nacido"],
        "direct": ["cuna", "cobija", "biberon", "juguete", "mantel", "vela"],
        "exclude": ["navidad", "halloween"],
        "exclude_categories": ["HERRAMIENTAS", "AUTOMOTRIZ"],
        "bridges": [{"label": "para su habitación", "terms": ["cuna", "cobija"]}],
    },
    "vuelta_a_clases": {
        "label": "vuelta a clases",
        "aliases": ["vuelta a clases", "regreso a clases", "útiles escolares", "utiles escolares"],
        "direct": ["cuaderno", "mochila", "lapiz", "cartuchera", "escritorio"],
        "exclude": [],
        "exclude_categories": ["AUTOMOTRIZ"],
        "bridges": [{"label": "para estudiar", "terms": ["escritorio", "lampara"]}],
    },
    "parrilla": {
        "label": "parrilla",
        "aliases": ["parrilla", "asado", "barbacoa", "bbq"],
        "direct": ["parrilla", "carbon", "utensilios", "tabla", "cuchillo"],
        "exclude": [],
        "exclude_categories": ["AUTOMOTRIZ"],
        "bridges": [{"label": "para servir", "terms": ["vajilla", "mantel"]}],
    },
    "vacaciones": {
        "label": "vacaciones",
        "aliases": [
            "vacaciones",
            "viaje",
            "viajar",
            "verano",
            "descanso",
            "entretenerme",
            "entretenimiento",
        ],
        "direct": [
            "televisor",
            "parlante",
            "altavoz",
            "sombrilla",
            "reposera",
            "cooler",
        ],
        "exclude": [
            "mueble",
            "silla",
            "mesa",
            "pintura",
            "herramienta",
            "colchon",
        ],
        "exclude_categories": [
            "MUEBLES",
            "HERRAMIENTAS",
            "PINTURA",
            "FERRETERIA",
            "AUTOMOTRIZ",
        ],
        "bridges": [
            {"label": "una noche de película", "terms": ["televisor", "tv"]},
            {"label": "música para el viaje", "terms": ["parlante", "altavoz"]},
            {"label": "aire libre", "terms": ["reposera", "sombrilla"]},
        ],
    },
}


def _load() -> dict:
    if not PATH.exists():
        return FALLBACK
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("occasions.json debe ser un objeto")
        valid = {}
        for key, value in data.items():
            if not isinstance(value, dict) or not value.get("label"):
                continue
            if not value.get("direct"):
                continue
            valid[str(key)] = value
        return valid or FALLBACK
    except Exception:  # noqa: BLE001 - el mapa aprobado no debe romper el bot
        logger.exception("No se pudo cargar occasions.json; uso fallback")
        return FALLBACK


EVENTS = _load()


def _aliases() -> dict[str, str]:
    result = {}
    for key, event in EVENTS.items():
        for alias in event.get("aliases") or [event.get("label", key)]:
            result[str(alias).lower()] = key
    return result


ALIASES = _aliases()
_EVENT_RE = re.compile(
    "|".join(
        re.escape(alias)
        for alias in sorted(ALIASES, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def detect(text: str | None) -> str | None:
    """Detecta el **tema** (ocasión) del mensaje, sin decidir la intención.

    Que la mención venga negada ("no, ya viajaré") no cambia el tema: quien
    decide si corresponde mostrar productos es el clasificador de intención.
    """
    match = _EVENT_RE.search(text or "")
    if not match:
        return None
    return ALIASES.get(match.group(0).lower())


def excluded(
    name: str, event: dict, category: str | None = None
) -> bool:
    folded = f"{name or ''} {category or ''}".lower()
    if any(
        term.lower() in folded
        for term in event.get("exclude_categories") or []
    ):
        return True
    return any(term in folded for term in event.get("exclude") or [])
