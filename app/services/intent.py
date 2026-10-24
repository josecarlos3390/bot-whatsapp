"""Clasificación de intención del mensaje.

Tres capas, de la más barata a la más cara:

1. **Reglas**: señales explícitas de compra (precio, cuánto, tienen, quiero…),
   saludos, preguntas y frases personales. Resuelve la mayoría en 0 ms.
2. **Contexto**: la negación ("no, ya viajaré") y la ambigüedad se detectan
   antes de decidir; si hay duda, no se asume.
3. **Modelo**: cuando las reglas no alcanzan, se llama al LLM con una **lista
   cerrada** de ocasiones y se le pide JSON estricto. Así no inventa categorías
   ni decide libremente: elige entre las que existen.

Los resultados se cachean por texto normalizado para no pagar dos veces la
misma frase y para que la respuesta sea consistente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from typing import Any

from openai import AsyncOpenAI

from ..config import settings
from . import occasions

logger = logging.getLogger(__name__)

INTENTS = ("producto", "personal", "pregunta", "saludo", "otro")

# Señales de que el cliente quiere comprar o ver algo concreto.
_BUY_TERMS = (
    "precio", "cuanto", "cuánto", "cuesta", "sale", "comprar", "compra",
    "quiero", "necesito", "busco", "buscando", "buscás", "buscas", "tenes",
    "tenés", "tienes", "tienen", "venden", "manejan", "hay", "mostrame",
    "mostrás", "mostrar", "recomenda",
    "recomendás", "recomendame", "promo", "promocion", "promoción", "oferta",
    "descuento", "stock", "disponible", "modelo", "marca", "cuotas",
    "combo", "presupuesto", "hasta cuanto", "barato",
    "economico", "económico", "mejor", "opciones", "opcion", "opción",
    "catalogo", "catálogo", "medida", "medidas", "color", "talle",
)

# Productos: si aparece uno, la frase casi siempre es una consulta de catálogo.
_PRODUCT_TERMS = (
    "colchon", "colchón", "almohada", "sabana", "sábana", "cama", "sommier",
    "respaldo", "sofa", "sofá", "sillon", "sillón", "mesa", "silla", "ropero",
    "placard", "comoda", "cómoda", "escritorio", "estante", "repisa",
    "tv", "televisor", "television", "televisión", "pantalla", "parlante",
    "audio", "heladera", "refrigerador", "refri", "lavadora", "lavarropas",
    "secadora", "microondas", "licuadora", "batidora", "freidora", "plancha",
    "ventilador", "aire", "split", "estufa", "calefactor", "aspiradora",
    "aspirador", "olla", "sarten", "sartén", "vajilla", "cubiertos", "vaso",
    "taza", "cortina", "alfombra", "toalla", "manta", "frazada", "edredon",
    "lampara", "lámpara", "foco", "bombilla", "espejo", "mueble", "comedor",
    "inodoro", "ducha", "grifo", "griferia", "grifería", "ceramica", "cerámica",
    "porcelanato", "pintura", "latex", "látex", "esmalte", "rodillo", "brocha",
    "taladro", "amoladora", "sierra", "destornillador", "llave", "tornillo",
    "clavo", "martillo", "cinta", "pegamento", "silicona", "cable", "foco led",
    "maceta", "planta", "parrilla", "reposera", "sombrilla", "cooler", "carpa",
    "maleta", "valija", "mochila", "juguete", "bicicleta", "pesas", "cinta de correr",
)

# Temas delicados: se responden con empatía, nunca con productos.
_SENSITIVE_TERMS = {
    "duelo": (
        "murio", "murió", "fallecio", "falleció", "perdi a", "perdí a",
        "se me murio", "se me murió", "muerte", "funeral", "velorio",
        "mascota", "mi perro", "mi gato",
    ),
    "salud": (
        "enfermo", "enferma", "hospital", "diagnostico", "diagnóstico",
        "cancer", "cáncer", "ansiedad", "depresion", "depresión",
        "operacion", "operación", "internado",
    ),
    "animo": (
        "triste", "tristeza", "solo", "sola", "mal", "angustia",
        "llorar", "llorando", "deprimido", "deprimida", "no estoy bien",
    ),
    "familia": (
        "divorcio", "separacion", "separación", "se murio mi", "se murió mi",
        "mi mama", "mi mamá", "mi papa", "mi papá",
    ),
    "dinero": (
        "despedido", "despedida", "sin trabajo", "deuda", "no tengo plata",
    ),
}

_PERSONAL_TERMS = (
    "te cuento", "viaj", "vacacion", "vacación", "mud", "mudanza",
    "casa nueva", "departamento nuevo", "me case", "me casé", "casamiento",
    "bebe", "bebé", "nacio", "nació", "embarazada", "familia", "cumple",
    "cumpleaños", "regalo", "ascend", "trabajo nuevo", "me quedo",
    "me quede", "me quedé", "estoy en casa", "descansar", "vacaciones",
)

_GREETING_RE = re.compile(
    r"^(hola|holas|buenas|buen dia|buen día|buenos dias|buenos días|"
    r"buenas tardes|buenas noches|que tal|qué tal|hey|hola que tal)\b",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(
    r"(\?|^(que|qué|como|cómo|cuando|cuándo|donde|dónde|quien|quién|"
    r"cuanto|cuánto|cual|cuál|cuales|por que|por qué|tenes|tenés|tienen|hay)\b)",
    re.IGNORECASE,
)

_NEGATION_RE = re.compile(r"^\s*(no|nunca|tampoco|al final no)\b", re.IGNORECASE)

# Charla social que no es una consulta ("qué haces", "cómo estás").
_SMALLTALK_RE = re.compile(
    r"^(que|qué) haces|^(como|cómo) est(?:as|ás)|^todo bien", re.IGNORECASE
)


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _has(text: str, terms: tuple[str, ...]) -> bool:
    folded = _fold(text)
    return any(_fold(term) in folded for term in terms)


def rules(text: str | None) -> dict[str, Any]:
    """Clasificación sin modelo. Devuelve intent, ocasión, compra y duda."""
    normalized = _normalize(text)
    folded = _fold(normalized)
    occasion = occasions.detect(normalized)
    buys = _has(normalized, _BUY_TERMS)
    mentions_product = _has(normalized, _PRODUCT_TERMS)
    personal = _has(normalized, _PERSONAL_TERMS)
    negated = bool(_NEGATION_RE.match(normalized))
    question = bool(_QUESTION_RE.search(normalized))

    sensitive_topic = next(
        (
            topic
            for topic, terms in _SENSITIVE_TERMS.items()
            if _has(normalized, terms)
        ),
        None,
    )

    if not normalized:
        intent = "otro"
    elif _GREETING_RE.match(folded) and len(folded.split()) <= 6 and not buys:
        intent = "saludo"
    elif buys or mentions_product:
        intent = "producto"
    elif personal:
        intent = "personal"
    elif _SMALLTALK_RE.search(folded):
        intent = "otro"
    elif question:
        intent = "pregunta"
    else:
        intent = "otro"

    # Una frase personal no se convierte en consulta por mencionar "viaje".
    if personal and not buys and not mentions_product:
        intent = "personal"

    # Duda real: cuenta un plan personal que además nombra una ocasión, o
    # niega algo sin decir qué quiere. Ahí conviene preguntar antes de asumir.
    ambiguous = bool(
        (intent == "personal" and negated)
        or (negated and not buys and not mentions_product and occasion)
        or (intent == "otro" and occasion and len(folded.split()) <= 8)
    )

    return {
        "intent": intent,
        "occasion": occasion,
        "buy": bool(buys or mentions_product),
        "ambiguous": ambiguous,
        "negated": negated,
        "sensitive": sensitive_topic is not None,
        "sensitive_topic": sensitive_topic,
        "source": "rules",
    }


_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_MAX = 2000
_CLIENT: AsyncOpenAI | None = None


def _cache_key(text: str) -> str:
    return hashlib.sha1(_normalize(text).encode("utf-8")).hexdigest()


def _client() -> AsyncOpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=2.5,
        )
    return _CLIENT


def _catalog_for_prompt() -> str:
    lines = []
    for key, event in occasions.EVENTS.items():
        label = event.get("label") or key
        lines.append(f"- {key}: {label}")
    return "\n".join(lines)


_SYSTEM = """Clasificás mensajes de clientes de un homecenter.
Respondé SOLO con JSON válido, sin explicaciones:

{
  "intent": "producto|personal|pregunta|saludo|otro",
  "occasion": "<clave de la lista o ninguna>",
  "compra": true|false,
  "ambiguo": true|false,
  "sensible": true|false,
  "tema_sensible": "duelo|salud|animo|familia|dinero|ninguno"
}

Reglas:
- "producto": pregunta por un artículo, precio, stock, modelo o pide recomendación.
- "personal": cuenta algo de su vida (viaje, mudanza, familia) sin pedir producto.
- "pregunta": otra consulta (envíos, horarios, garantía, pagos, sucursales).
- "saludo": solo saluda.
- "otro": no encaja.
- "compra" es true solo si hay intención explícita de ver o comprar algo.
- "ambiguo" es true si la frase puede significar dos cosas y conviene preguntar
  (por ejemplo "no, ya viajaré": ¿se va o se queda?).
- Si nombra un plan personal, occasion puede ser su clave aunque compra sea false.
- "sensible" es true ante duelo, enfermedad, tristeza, problemas familiares o
  de dinero. En esos casos NO hay que ofrecer productos.
- Nunca inventes una ocasión: usá una de la lista o "ninguna"."""


async def _llm(text: str) -> dict[str, Any] | None:
    if not settings.deepseek_api_key:
        return None
    try:
        response = await _client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Ocasiones disponibles:\n{_catalog_for_prompt()}\n\n"
                        f"Mensaje: {text[:400]}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=120,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:  # noqa: BLE001 - el clasificador nunca frena al bot
        logger.debug("Clasificación por modelo falló", exc_info=True)
        return None

    intent = str(data.get("intent") or "otro").lower()
    if intent not in INTENTS:
        intent = "otro"
    occasion = str(data.get("occasion") or "ninguna").lower()
    if occasion in ("ninguna", "none", "", "null"):
        occasion = None
    elif occasion not in occasions.EVENTS:
        occasion = None
    topic = str(data.get("tema_sensible") or "ninguno").lower()
    if topic in ("ninguno", "none", "", "null"):
        topic = None
    return {
        "intent": intent,
        "occasion": occasion,
        "buy": bool(data.get("compra")),
        "ambiguous": bool(data.get("ambiguo")),
        "negated": False,
        "sensitive": bool(data.get("sensible")) or topic is not None,
        "sensitive_topic": topic,
        "source": "llm",
    }


async def classify(text: str | None, *, use_llm: bool = True) -> dict[str, Any]:
    """Devuelve la intención del mensaje, con caché y respaldo por reglas."""
    key = _cache_key(text or "")
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    result = rules(text)
    # Las reglas alcanzan cuando hay señal clara de compra o es un saludo.
    needs_model = (
        settings.deepseek_api_key
        and use_llm
        and not result.get("sensitive")
        and result["intent"] in ("otro", "personal", "pregunta")
        and (result["ambiguous"] or not result["buy"])
    )
    if needs_model:
        model = await _llm(text or "")
        if model is not None:
            merged = {**model}
            # Preguntar es más seguro que asumir: si las reglas ven duda
            # (una negación, por ejemplo), la duda se mantiene.
            merged["ambiguous"] = bool(
                model.get("ambiguous") or result["ambiguous"]
            )
            merged["negated"] = result["negated"]
            # Ante un tema delicado, la regla manda: siempre empatía.
            merged["sensitive"] = bool(
                model.get("sensitive") or result.get("sensitive")
            )
            merged["sensitive_topic"] = (
                result.get("sensitive_topic") or model.get("sensitive_topic")
            )
            if not merged.get("occasion"):
                merged["occasion"] = result["occasion"]
            # Las reglas no se dejan pisar cuando encuentran algo concreto:
            # si detectaron compra o una frase personal, eso manda.
            if merged["intent"] == "otro" and result["intent"] in (
                "personal",
                "producto",
                "saludo",
            ):
                merged["intent"] = result["intent"]
            result = merged

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = result
    return result
