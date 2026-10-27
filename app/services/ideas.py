"""Ideas por intención: "algo para distraer a las visitas".

Cuando el cliente pide una idea y no un producto, buscar por la frase completa
devuelve cualquier cosa (una vela de citronela). Acá se traduce la intención a
categorías concretas del catálogo y se explican las opciones.
"""

from __future__ import annotations

import re

# Cada intención: frases que la activan y las ideas con su explicación.
INTENCIONES = (
    {
        "clave": "visitas",
        "label": "entretener a las visitas",
        "frases": (
            r"distraer\s+(a\s+)?(las\s+)?visitas",
            r"entretener\s+(a\s+)?(las\s+)?(visitas|invitados|chicos|ni[nñ]os)",
            r"tengo\s+visitas",
            r"vienen\s+(visitas|invitados|gente)",
            r"recibir\s+(visitas|invitados|gente)",
            r"reuni[oó]n\s+en\s+casa",
        ),
        "ideas": (
            {
                "terminos": ("televisor", "tv"),
                "frase": "un televisor para poner una película o un partido",
            },
            {
                "terminos": ("parlante", "altavoz", "equipo de sonido"),
                "frase": "audio para música de ambiente",
                "excluir": ("espanta", "insectos", "repelente", "mosca"),
            },
            {
                "terminos": ("juego de mesa", "juegos de mesa"),
                "frase": "juegos de mesa para compartir",
                "excluir": ("exterior", "sillas", "jardín", "jardin"),
            },
        ),
    },
    {
        "clave": "musica",
        "label": "música en casa",
        "frases": (
            r"m[uú]sica\s+(de\s+)?ambiente",
            r"poner\s+m[uú]sica",
            r"escuchar\s+m[uú]sica",
            r"parlantes?",
            r"algo\s+de\s+(m[uú]sica|audio|sonido)",
            r"m[uú]sica\s+para\s+(la\s+)?(casa|el\s+living|living)",
        ),
        "ideas": (
            {
                "terminos": ("parlante", "altavoz", "equipo de sonido"),
                "frase": "audio para música de ambiente",
                "excluir": ("espanta", "insectos", "repelente", "mosca"),
            },
            {
                "terminos": ("televisor", "tv"),
                "frase": "un televisor con sonido para acompañar",
            },
        ),
    },
    {
        "clave": "pelicula",
        "label": "noche de película",
        "frases": (
            r"noche\s+de\s+pel[ií]cula",
            r"ver\s+(una\s+)?pel[ií]cula",
            r"proyectar",
        ),
        "ideas": (
            {
                "terminos": ("televisor", "tv"),
                "frase": "un televisor para la película",
            },
            {
                "terminos": ("soporte para tv", "soporte"),
                "frase": "un soporte para dejarlo cómodo",
            },
        ),
    },
)

_COMPILADAS = [
    (
        intencion,
        [re.compile(frase, re.IGNORECASE) for frase in intencion["frases"]],
    )
    for intencion in INTENCIONES
]


def detect(text: str) -> dict | None:
    """Intención de recomendación detectada en el mensaje."""
    valor = (text or "").strip()
    if len(valor) < 8:
        return None
    for intencion, patrones in _COMPILADAS:
        if any(patron.search(valor) for patron in patrones):
            return intencion
    return None
