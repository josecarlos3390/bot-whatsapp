from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import context, persona
from .config import settings
from .models import (
    CatalogItem,
    Contact,
    Conversation,
    FunnelEvent,
    Handoff,
    Message,
    ProductPromotion,
)
from .services import (
    cart as cart_service,
    catalog,
    area_router,
    coherence,
    conversation_state,
    media as media_service,
    vision,
    ideas,
    conversation_guard,
    customer_analysis,
    funnel,
    intent as intent_service,
    intent_guard,
    customers,
    feedback,
    handoffs,
    knowledge,
    memory as memory_service,
    metrics,
    session_flow,
    native_commerce,
    orders,
    policy as policy_guard,
    preferences,
    pricing,
    purchases,
    order_tracking,
    occasions,
    occasion_store,
    recommendations,
    return_flow,
    rule_policy,
    rules_engine,
    learning,
    semantic,
    understanding,
    sales_stats,
    vtex_customers,
)
from .sap import SapError, ServiceLayerSap, get_sap
from .whatsapp import Outbound, WhatsAppClient, normalize_whatsapp_text

logger = logging.getLogger(__name__)

_TOOL_TRACE = Path("logs") / "bot_tools.jsonl"


def _log_tool_trace(name: str, arguments: dict, result: dict) -> None:
    """Auditoría local de tool calls para revisar errores de interpretación."""
    try:
        _TOOL_TRACE.parent.mkdir(exist_ok=True)
        with _TOOL_TRACE.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "tool": name,
                        "args": arguments,
                        "ok": result.get("ok"),
                        "error": str(result.get("error") or "")[:300],
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001 - la trazabilidad no debe romper el bot
        logger.debug("No se pudo escribir tool trace", exc_info=True)


def money(amount: Decimal | int | float | str) -> str:
    value = Decimal(amount).quantize(Decimal("0.01"))
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"Bs {formatted}"


_STOPWORDS = {
    # Conectores de cambio de tema: "ahora quiero alfombras" -> "alfombras".
    "ahora",
    "despues",
    "después",
    "luego",
    "tambien",
    "también",
    # Ruido de conversación: "no me gusta, mejor quiero tv" debe quedar "tv".
    "no",
    "nada",
    "gusta",
    "gustan",
    "mejor",
    "peor",
    "eso",
    "esa",
    "ese",
    "quiero",
    "necesito",
    "busco",
    "buscame",
    "buscar",
    "buscando",
    "buscaba",
    "estoy",
    "comprar",
    "compro",
    "deseo",
    "quisiera",
    "ver",
    "opciones",
    "mostrar",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "para",
    "por",
    "favor",
    "hola",
    "me",
    "mi",
    "mis",
    "tu",
    "tus",
    "su",
    "sus",
    "puedes",
    "mostrar",
    "tienes",
    "tiene",
    "tienen",
    "hay",
    "el",
    "la",
    "los",
    "las",
    "y",
    "o",
    "en",
    "algo",
}


def _clean_query(text: str) -> str:
    value = re.sub(r"[^\wáéíóúñü]+", " ", (text or "").lower())
    words = [w for w in value.split() if w]
    return " ".join(w for w in words if w not in _STOPWORDS)


TV_QUERY_RE = re.compile(
    r"\b(televisor(?:es)?|television(?:es)?)\b", re.IGNORECASE
)
TV_INTENT_RE = re.compile(
    r"\b(tv|televisor(?:es)?|television(?:es)?)\b", re.IGNORECASE
)
TV_NAME_RE = re.compile(r"^\s*TV\b", re.IGNORECASE)


def _normalize_tv_query(text: str) -> str:
    """'televisor' se busca como 'tv': así aparecen todos los TVs y no
    sólo los que tienen la palabra en categoría."""
    return TV_QUERY_RE.sub("tv", text or "")


def _only_tvs(products: list[dict]) -> list[dict]:
    filtered = [
        product
        for product in products
        if TV_NAME_RE.match(str(product.get("name") or ""))
    ]
    return filtered or products


def _semantic_term_match(product: dict, term: str) -> bool:
    """Evita que 'baby shower' termine recomendando una ducha o Babyliss."""
    tokens = [
        _fold_word(token)
        for token in re.split(r"[^\wáéíóúñü]+", term)
        if len(token) > 2
    ]
    if not tokens:
        return False
    blob = _fold_word(
        f"{product.get('name') or ''} {product.get('category') or ''}"
    )
    for token in tokens:
        if token in blob or token.rstrip("s") in blob:
            continue
        if token in {"televisor", "television", "televisores"} and "tv" in blob:
            continue
        return False
    return True


def _conversational_search(text: str) -> bool:
    """¿La búsqueda viene en una frase conversacional?

    Las frases largas se derivan al agente LLM para que sintetice la consulta
    y redacte la respuesta; las palabras sueltas siguen el atajo rápido.
    """
    words = re.findall(r"[a-záéíóúñü]+", _fold_word(text))
    if len(words) < 4:
        return False
    fillers = {
        "estoy",
        "buscando",
        "busco",
        "quiero",
        "comprar",
        "necesito",
        "quisiera",
        "deseo",
        "hola",
        "buenas",
        "ayudame",
        "podrias",
        "gustaria",
        "para",
        "mi",
        "de",
        "un",
        "una",
    }
    return any(word in fillers for word in words)


def _remove_query_echo(answer: str, text: str) -> str:
    """Evita que la IA repita la frase cruda del cliente como título."""
    raw = (text or "").strip()
    clean = _clean_query(raw)
    if raw and clean and raw.lower() != clean.lower():
        for left, right in (
            (f"*{raw}*", f"*{clean}*"),
            (f"“{raw}”", f"“{clean}”"),
            (f'"{raw}"', f'"{clean}"'),
        ):
            answer = answer.replace(left, right)
    return answer


def _is_personal_statement(text: str) -> bool:
    """¿Es una frase personal ("ya viajaré", "me mudé") y no un pedido?

    En esos casos conviene reconocer, preguntar si es ambiguo y recién ahí
    ofrecer algo: listar productos "cercanos" suena a que no entendimos.
    """
    folded = (text or "").lower().strip()
    if not folded or "?" in folded:
        return False
    words = folded.split()
    if len(words) > 14:
        return False
    buy_terms = (
        "precio", "cuanto", "cuánto", "cuesta", "comprar", "quiero",
        "necesito", "busco", "buscá", "buscas", "tenes", "tenés", "tienen",
        "mostrame", "mostrás", "recomenda", "recomendás", "promo", "oferta",
        "stock", "modelo", "marca", "cuotas", "envio", "envío",
    )
    if any(term in folded for term in buy_terms):
        return False
    personal = (
        "te cuento", "viaj", "vacacion", "mudo", "mudanza", "casa nueva",
        "me case", "me casé", "bebe", "bebé", "nacio", "nació", "familia",
        "cumple", "regalo", "ascend", "trabajo nuevo", "me quedo",
    )
    if any(term in folded for term in personal):
        return True
    return folded.startswith(("no,", "no ", "si,", "sí,"))


def _requested_size(text: str) -> str | None:
    """Extrae '50 pulgadas', '50"' o '50 plg' como filtro de medida."""
    match = re.search(
        r'\b(\d{2,3})\s*(?:pulgadas?|pulg\.?|plg\.?|"|in)(?=\s|$|[.,;])',
        text or "",
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _requested_quantity(text: str) -> int:
    """Cantidad explícita: '3 televisores', '2 unidades', 'quiero 4'."""
    match = re.search(
        r"\b(?:quiero|necesito|comprar|llevar|encargar|pedir)\s+"
        r"(\d{1,3})\b"
        r"|\b(\d{1,3})\s*(?:unidades?|piezas?|televisores?|"
        r"heladeras?|colchones?|lavadoras?|aires?|muebles?)\b",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return 1
    return max(1, int(match.group(1) or match.group(2)))


def _amount(value: str) -> float:
    raw = (value or "").replace(" ", "").replace("Bs", "").replace("BOB", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif "." in raw and len(raw.rsplit(".", 1)[-1]) == 3:
        raw = raw.replace(".", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    return float(raw)


def _requested_budget(text: str) -> tuple[float | None, float | None]:
    """Extrae presupuesto explícito. No interpreta cualquier número."""
    value = text or ""
    between = re.search(
        r"\bentre\s+([\d.,]+)\s+y\s+([\d.,]+)\b", value, re.IGNORECASE
    )
    if between:
        try:
            low, high = _amount(between.group(1)), _amount(between.group(2))
            return min(low, high), max(low, high)
        except ValueError:
            return None, None
    maximum = re.search(
        r"\b(?:presupuesto(?:\s+de)?|hasta|m[aá]ximo|m[aá]x\.?|"
        r"no\s+m[aá]s\s+de|menos\s+de|tope)\s*"
        r"(?:bs\.?|bob)?\s*([\d.,]+)\b",
        value,
        re.IGNORECASE,
    )
    if maximum:
        try:
            return None, _amount(maximum.group(1))
        except ValueError:
            return None, None
    return None, None


def _strip_budget(text: str) -> str:
    value = re.sub(
        r"\b(?:presupuesto(?:\s+de)?|hasta|m[aá]ximo|m[aá]x\.?|"
        r"no\s+m[aá]s\s+de|menos\s+de|tope)\s*"
        r"(?:bs\.?|bob)?\s*[\d.,]+\b",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\bentre\s+[\d.,]+\s+y\s+[\d.,]+\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", value).strip()


def _strip_quantity(text: str, quantity: int) -> str:
    if quantity <= 1:
        return text
    value = re.sub(
        rf"\b{quantity}\s*(?:unidades?|piezas?)\b",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    value = re.sub(rf"\b{quantity}\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _numbered_lines(values: list[str]) -> str:
    return "\n".join(
        f"{index}. {value}" for index, value in enumerate(values, start=1)
    )


def _remove_stock_phrases(answer: str) -> str:
    """La ficha/tarjetas no muestran stock; quitamos frases sueltas del LLM."""
    answer = re.sub(r"\s+en stock\b", "", answer, flags=re.IGNORECASE)
    answer = re.sub(
        r"\bstock\s*[:=]?\s*\d+\b", "", answer, flags=re.IGNORECASE
    )
    answer = re.sub(
        r"\b(queda|quedan)\s+\d+\s+unidad(?:es)?\b",
        "",
        answer,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[ \t]{2,}", " ", answer).strip()


def _fold_word(value: str) -> str:
    """Minúsculas y sin acentos, para comparar títulos y consultas."""
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(
        ch for ch in normalized if not unicodedata.combining(ch)
    ).lower().strip()


@dataclass
class AgentReply:
    messages: list[Outbound] = field(default_factory=list)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Busca productos del catálogo por texto, categoría, marca, "
                "rango de precio o solo con descuento. Extraé la palabra clave "
                "de la frase del cliente; no pases la frase completa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto libre; puede omitirse si se usan filtros.",
                    },
                    "category": {"type": "string"},
                    "brand": {"type": "string"},
                    "size": {"type": "string"},
                    "min_price": {"type": "number", "minimum": 0},
                    "max_price": {"type": "number", "minimum": 0},
                    "only_discount": {"type": "boolean"},
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Cantidad que el cliente quiere comprar.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_catalog_facets",
            "description": (
                "Devuelve marcas, medidas y cantidad de productos con stock "
                "para una categoría. Usar para preguntas como '¿tienen "
                "televisores?' antes de listar modelos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_catalog",
            "description": (
                "Muestra un catálogo nativo filtrado (marca, categoría, precio "
                "o descuento). Usar solo si el catálogo nativo está activo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "brand": {"type": "string"},
                    "size": {"type": "string"},
                    "min_price": {"type": "number", "minimum": 0},
                    "max_price": {"type": "number", "minimum": 0},
                    "only_discount": {"type": "boolean"},
                    "quantity": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Cantidad que el cliente quiere comprar.",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": (
                "Devuelve la ficha, precio, descuento por período/cantidad y "
                "stock por tienda de un SKU exacto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_products",
            "description": (
                "Compara dos artículos (precio, marca, medida, stock, "
                "escalones) para ayudar al cliente a elegir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_a": {"type": "string"},
                    "sku_b": {"type": "string"},
                },
                "required": ["sku_a", "sku_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_promotions",
            "description": (
                "Lista promociones vigentes (descuento por período) con stock. "
                "Úsala cuando el cliente pregunte por ofertas, promociones o "
                "descuentos, o para sugerir alternativas con descuento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                    "min_discount": {"type": "number", "minimum": 0},
                    "min_price": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Precio base mínimo; por defecto 20 Bs.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": (
                "Devuelve el perfil y la memoria del cliente: ciudad, tienda, "
                "preferencias y resumen de conversaciones previas."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_best_sellers",
            "description": (
                "Devuelve los productos más vendidos con stock, por unidades "
                "de los últimos 30/90 días. Usar si no hay promo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Busca en la base de conocimiento: envíos, garantías, "
                "devoluciones, horarios, direcciones y pagos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_analysis",
            "description": (
                "Devuelve el análisis comercial del cliente: recencia, "
                "frecuencia, monto, ticket promedio, categorías y segmento."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_customer_fact",
            "description": (
                "Guarda una preferencia estable del cliente. Solo usar si el "
                "cliente dio permiso explícito (consent=true)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": (
                            "ciudad, zona, tienda_preferida, ocasion, "
                            "presupuesto, estilo, color, talla, "
                            "categoria_favorita, marca_favorita, tiene_mascota, "
                            "tipo_vivienda, no_contactar, nota"
                        ),
                    },
                    "value": {"type": "string"},
                    "consent": {"type": "boolean"},
                },
                "required": ["key", "value", "consent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_purchase_history",
            "description": (
                "Devuelve las compras del cliente: cantidad, total, última "
                "compra, categorías y facturas recientes con productos. "
                "Usar cuando pregunte por sus compras, historial, gasto, "
                "pedidos o facturas; no usar search_products para eso. "
                "Si linked=false, pedir CI o NIT antes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_for_customer",
            "description": (
                "Recomienda productos con promoción según las categorías que "
                "el cliente ya compró. Úsala para venta cruzada o recompra."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "need": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "identify_customer",
            "description": (
                "Busca un cliente en SAP por carnet o NIT (LicTradNum / "
                "FederalTaxID). Solo usar con consentimiento explícito. "
                "No vincula automáticamente: devuelve candidatos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document": {
                        "type": "string",
                        "description": "Carnet o NIT, sin puntos.",
                    },
                    "consent": {"type": "boolean"},
                },
                "required": ["document", "consent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "link_customer",
            "description": (
                "Vincula el contacto con el cliente confirmado (CardCode en "
                "SAP o documento en VTEX) y sincroniza su historial de compras. "
                "Solo tras confirmar nombre."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "card_code": {"type": "string"},
                    "document": {"type": "string"},
                    "consent": {"type": "boolean"},
                },
                "required": ["card_code", "consent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Agrega unidades de un SKU al carrito del cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                    "store": {
                        "type": "string",
                        "description": (
                            "Código de tienda: 101-1001, 102-1001 o 103-1001. "
                            "Opcional; si no se indica se elige una con stock."
                        ),
                    },
                },
                "required": ["sku", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Quita un producto completo del carrito.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart_quantity",
            "description": (
                "Cambia la cantidad de un producto del carrito. "
                "Si la cantidad es 0, lo quita."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 0},
                },
                "required": ["sku", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_cart",
            "description": "Vacía el carrito completo del cliente.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "Muestra el carrito actual con totales.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout",
            "description": (
                "Crea el pedido y genera el link/QR de pago. Usar sólo cuando el "
                "cliente confirmó explícitamente el pedido."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "order_status",
            "description": "Consulta el último pedido del cliente.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_recommendation",
            "description": (
                "Explica con datos reales por qué se recomendaron los "
                "productos anteriores: precio, descuento, disponibilidad, "
                "marca o medida. No inventes criterios."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "human_handoff",
            "description": "Deriva la conversación a un asesor humano.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

SYSTEM_PROMPT = """Eres Rohi, la asesora virtual de ROHO Homecenter en Bolivia.
Vendés por WhatsApp: ayudás a encontrar lo que el cliente necesita y cerrás
la venta sin presionar.

Tono:
- Cálida y resolutiva, como una asesora de tienda que conoce los productos.
- Español boliviano, tuteo, máximo 5 líneas por respuesta.
- Emojis: máximo 1 por mensaje y nunca en reclamos ni temas serios.
- Humor breve y ocasional solo si el cliente está relajado; cero humor en
  precio, stock, pagos, reclamos, datos personales o si está molesto.
- No repitas el saludo ni el nombre en cada mensaje. Saludá según la hora.
- No digas "estimado cliente", "soy un robot" ni "encontré estas opciones".

Estilo:
- Respondé primero lo que preguntó; después UNA sola pregunta.
- Nunca muestres stock ni cantidades; si preguntan, respondé sí o no.
- No repitas la frase textual del cliente: nombrá el producto o la categoría.
- Si escribe con errores o abrevia (air, televisro, refri), inferí la
  categoría. Si hay duda real, preguntá "¿Te referís a ...?".
- Enumerá marcas o medidas una por línea.
- Si ya dijo qué busca, mostrale 2-3 opciones con precio y después preguntá
  medida, estilo o presupuesto. No lo interrogues antes de dar valor.
- En un reclamo: "Lamento lo ocurrido", disculpa breve, solución o derivación.

Método de venta:
1. Descubrí la necesidad (uso, espacio, presupuesto, estilo).
2. Buscá con search_products y recomendá 1 o 2 opciones concretas con precio.
   Si menciona una categoría concreta, buscá antes de preguntar medida o marca.
   Si pregunta "tenés televisores", usá get_catalog_facets y ofrecé las marcas
   reales antes de listar modelos.
   Filtros: category, brand, only_discount, max_price (no mandes todo el catálogo).
   Si no hay con descuento, la herramienta devuelve alternativas: explicá que
   no hay promo y ofrecé esas al precio normal. Para ordenar por ventas reales,
   usá get_best_sellers; no inventes "más vendido".
   Usá el precio que devuelve la herramienta (promo_price es el final) y sus
   notas; nunca calcules ni inventes descuentos.
3. Si pregunta por promociones, usá list_promotions con descuento y vigencia.
4. Varias unidades: get_product con quantity para ver el escalón y sugeri el
   que convenga. Para el carrito: add_to_cart, remove_from_cart,
   update_cart_quantity, clear_cart, view_cart; confirmá con el resultado.
5. Ofrecé un complemento o una tienda con stock, sin empujar.
6. Cerrá con una pregunta simple: "¿Te lo agrego?".

Seguimiento de pedido:
- "Estado", "seguimiento" o "mi pedido": pedí el ID que VTEX envió al correo
  (ej. 1670220500193-01). No pidas CI/NIT para eso.
- No inventes estado, fecha, guía ni transportista; si no aparece, derivá.

Compras del cliente:
- Para historial, factura o "cuánto gasté": pedí CI/NIT con consentimiento y
  usá identify_customer. Mostrá el nombre enmascarado y confirmá; si acepta,
  link_customer con el card_code. Después get_purchase_history.
- No pidas CI/NIT para consultas de producto, precio o stock.
- Si no hay compras, decilo; si linked=false, primero identificá.

Objeciones y confianza:
- Si dice que está caro, no discutas: 1 o 2 alternativas más económicas con
  stock o el escalón por cantidad. Nunca bajes el precio ni inventes descuentos.
- Mencioná la marca cuando aporte confianza, solo desde el dato real.
- Nunca ofrezcas artículos sin stock; usá el stock internamente.
- Si duda entre dos modelos, compare_products y compará 2-3 puntos concretos.

Derivación:
- Derivá solo si lo pide o si el tema no es de producto (reclamo, facturación,
  algo que no resuelve el catálogo). No derives lo que podés responder con
  precios o alternativas. Si derivás, seguí atendiendo consultas de producto.

Temas delicados (duelo, enfermedad, tristeza, familia o dinero):
- Empatía breve, sin emojis festivos y sin vender.
- No ofrezcas productos ni fotos.
- Decí que tu función es ayudar con productos del hogar y ofrecé una persona
  del equipo.
- No des consejos médicos, legales ni financieros.

Algo personal (viaje, mudanza, bebé, fiesta) sin pedir producto:
- Reconocelo en una frase ("¡Ah, se viene viaje!").
- Si es ambiguo, preguntá qué quiso decir antes de asumir.
- Después ofrecé UNA cosa concreta y preguntá si le sirve. Nada de listas
  largas ni de "no tengo una sección de X".

Memoria y datos:
- Usá lo que ya sabés del cliente y no vuelvas a preguntar lo mismo.
- Si cuenta una preferencia estable, preguntá si podés recordarla y usá
  remember_customer_fact solo si acepta.
- No pidas carnet, tarjeta ni datos sensibles en el chat (salvo CI/NIT para
  historial, con consentimiento explícito).

Conocimiento:
- Envíos, garantías, devoluciones, horarios, pagos o políticas:
  search_knowledge. Si no hay dato publicado, decí que no lo tenés confirmado
  y ofrecé derivar. No inventes políticas ni plazos.

Reglas:
- Usá SIEMPRE las herramientas para precio, stock, descuentos y pedidos.
- Si indica cantidad, pasala en quantity; presupuesto en min_price/max_price.
- Si pregunta por qué recomendaste algo, explicá criterios reales (precio,
  descuento, disponibilidad, marca, medida) sin inventar calidad.
- Nunca inventes promociones, descuentos, stock, plazos, reseñas ni urgencia.
- No pidas tarjeta ni datos bancarios: el pago es por QR o link.
- Si el cliente se molesta o el caso es complejo, human_handoff.
"""


class Toolbox:
    def __init__(
        self,
        session: AsyncSession,
        contact: Contact,
        wa: WhatsAppClient | None = None,
    ):
        self.session = session
        self.contact = contact
        self.contact_id = contact.id
        self.wa = wa
        self.last_checkout: dict | None = None
        self.last_catalog: dict | None = None
        self.last_cart: bool = False
        self.last_search: dict | None = None

    async def _remember_search_context(self, query: str) -> None:
        """Guarda el rubro/marca para que el siguiente mensaje no pierda contexto."""
        value = (query or "").strip()
        if not value:
            return
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.contact_id == self.contact_id
            )
        )
        if conversation is None:
            conversation = Conversation(contact_id=self.contact_id)
            self.session.add(conversation)
        conversation.last_query = value[:300]
        await self.session.commit()

    async def _update_state(self, **kwargs) -> None:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.contact_id == self.contact_id
            )
        )
        if conversation is None:
            conversation = Conversation(contact_id=self.contact_id)
            self.session.add(conversation)
            await self.session.flush()
        await conversation_state.update_state(
            self.session, conversation.id, **kwargs
        )

    async def _current_state(self):
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.contact_id == self.contact_id
            )
        )
        if conversation is None:
            conversation = Conversation(contact_id=self.contact_id)
            self.session.add(conversation)
            await self.session.flush()
        return await conversation_state.get_state(
            self.session, conversation.id
        )

    async def dispatch(self, name: str, arguments: dict) -> dict:
        method = getattr(self, f"tool_{name}", None)
        if method is None:
            return {"ok": False, "error": f"Herramienta desconocida: {name}"}
        try:
            result = await method(**arguments)
            logger.info(
                "tool=%s args=%s ok=%s error=%s",
                name,
                arguments,
                result.get("ok"),
                str(result.get("error") or "")[:200],
            )
            _log_tool_trace(name, arguments, result)
            return result
        except TypeError as exc:
            return {"ok": False, "error": f"Argumentos inválidos: {exc}"}
        except Exception as exc:  # noqa: BLE001 - el LLM debe recibir el error
            logger.exception("Error en herramienta %s", name)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _product(item) -> dict:
        data = {
            "sku": item.sku,
            "name": item.name,
            "price": str(item.price),
            "currency": item.currency,
            "stock": item.stock,
            "category": getattr(item, "category", None),
            "brand": getattr(item, "brand", None),
            "image_url": getattr(item, "image_url", None),
            "description": getattr(item, "description", None),
        }
        # Especificaciones (garantía, medidas, material…) para que el asesor
        # pueda filtrar y argumentar sin abrir la ficha.
        attributes = getattr(item, "attributes", None)
        if isinstance(attributes, dict):
            specs = attributes.get("specs")
            if isinstance(specs, dict) and specs:
                data["specs"] = dict(list(specs.items())[:6])
        return data

    async def _attach_promotions(self, products: list[dict]) -> None:
        skus = [product["sku"] for product in products]
        if not skus:
            return
        today = date.today()
        rows = (
            await self.session.scalars(
                select(ProductPromotion)
                .where(
                    ProductPromotion.sku.in_(skus),
                    ProductPromotion.price_list == settings.sap_price_list,
                    or_(
                        ProductPromotion.valid_from.is_(None),
                        ProductPromotion.valid_from <= today,
                    ),
                    or_(
                        ProductPromotion.valid_to.is_(None),
                        ProductPromotion.valid_to >= today,
                    ),
                )
                .order_by(ProductPromotion.discount_percent.desc())
            )
        ).all()
        periods: dict[str, ProductPromotion] = {}
        tiers: dict[str, dict[int, ProductPromotion]] = {}
        for promo in rows:
            if promo.tier_quantity is None:
                periods.setdefault(promo.sku, promo)
            else:
                tiers.setdefault(promo.sku, {}).setdefault(
                    promo.tier_quantity, promo
                )
        for product in products:
            base = Decimal(product["price"])
            promo = periods.get(product["sku"])
            if promo is not None and promo.price > 0 and base > 0:
                if promo.price < base:
                    discount = (
                        (base - Decimal(promo.price)) / base * 100
                    ).quantize(Decimal("0.01"))
                    product["promo_price"] = str(promo.price)
                    product["promo_discount_percent"] = str(discount)
                    product["promo_valid_to"] = (
                        promo.valid_to.isoformat() if promo.valid_to else None
                    )
            if product["sku"] in tiers and base > 0:
                quantity_tiers = []
                for quantity, tier in sorted(tiers[product["sku"]].items()):
                    if tier.price <= 0 or tier.price >= base:
                        continue
                    discount = (
                        (base - Decimal(tier.price)) / base * 100
                    ).quantize(Decimal("0.01"))
                    quantity_tiers.append(
                        {
                            "quantity": quantity,
                            "price": str(tier.price),
                            "discount_percent": str(discount),
                            "valid_to": (
                                tier.valid_to.isoformat()
                                if tier.valid_to
                                else None
                            ),
                        }
                    )
                if quantity_tiers:
                    product["quantity_tiers"] = quantity_tiers

    async def _refresh_live_prices(
        self, products: list[dict], limit: int = 5
    ) -> None:
        """Actualiza precio y stock de los primeros resultados contra SAP.

        La lista sale del catálogo (sync diario); sin esto, un cambio de precio
        se vería recién al abrir la ficha. Responde con lo que SAP conteste en
        ~1 segundo y deja el resto calentando en segundo plano: la próxima
        consulta ya tiene el precio vivo sin hacer esperar al cliente.
        """
        targets = [p for p in products[:limit] if p.get("sku")]
        if not targets or settings.sap_mode not in {"paas", "service_layer", "vtex"}:
            return

        adapter = None
        try:
            adapter = get_sap(self.session)
            pending_map: dict[asyncio.Task, dict] = {
                asyncio.ensure_future(self._live_offer(adapter, product["sku"])): product
                for product in targets
            }
            done, pending = await asyncio.wait(
                pending_map.keys(), timeout=1.2
            )
        except Exception:  # noqa: BLE001 - la lista ya tiene precio de catálogo
            logger.info(
                "Sin refresco de precios en vivo para la lista", exc_info=True
            )
            await self._close_sap(adapter)
            return

        for task in done:
            try:
                offer = task.result()
            except Exception:  # noqa: BLE001
                continue
            if offer is not None:
                self._apply_live_offer(pending_map[task], offer)

        if pending:
            # No se cancela: que termine y llene la caché para la próxima.
            asyncio.create_task(self._warm_and_close(pending, adapter))
        else:
            await self._close_sap(adapter)

    @staticmethod
    async def _live_offer(adapter, sku: str):
        try:
            return await adapter.get_offer(sku, 1)
        except Exception:  # noqa: BLE001 - un SKU no debe romper la lista
            return None

    @staticmethod
    async def _close_sap(adapter) -> None:
        closer = getattr(adapter, "close", None) if adapter is not None else None
        if closer is None:
            return
        try:
            await closer()
        except Exception:  # noqa: BLE001 - cerrar no debe romper nada
            logger.debug("No se pudo cerrar el adaptador SAP", exc_info=True)

    @classmethod
    async def _warm_and_close(cls, tasks, adapter) -> None:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await cls._close_sap(adapter)

    @staticmethod
    def _apply_live_offer(product: dict, offer) -> None:
        product["price"] = str(offer.base_price)
        if offer.final_price != offer.base_price:
            product["promo_price"] = str(offer.final_price)
            product["promo_discount_percent"] = str(
                offer.discount_percent or 0
            )
        # SAP puede devolver negativo por ajustes; para el cliente es 0.
        stock = max(0, sum((offer.stock_by_store or {}).values()))
        product["stock"] = stock

    async def _search_with_hot_cache(self, query: str, limit: int) -> list:
        """Busca en local y, si no hay, en SAP; lo traído queda en el catálogo."""
        if not settings.sap_hot_search_enabled:
            return await catalog.search_items(self.session, query, limit=limit)

        sap = None
        try:
            sap = get_sap(self.session)
            return await catalog.search_with_sap(
                self.session, query, sap=sap, limit=limit
            )
        except Exception:  # noqa: BLE001 - la búsqueda local sigue disponible
            logger.exception("Búsqueda en caliente no disponible para %s", query)
            return await catalog.search_items(self.session, query, limit=limit)
        finally:
            closer = getattr(sap, "close", None) if sap is not None else None
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001 - cerrar no debe romper nada
                    logger.debug("No se pudo cerrar el adaptador SAP", exc_info=True)

    async def tool_search_products(
        self,
        query: str | None = None,
        limit: int = 5,
        category: str | None = None,
        brand: str | None = None,
        size: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        only_discount: bool = False,
        quantity: int = 1,
        ignore_state: bool = False,
    ) -> dict:
        take = min(int(limit or 5), 8)
        # Código de barra: si el mensaje trae un EAN/UPC, se resuelve directo.
        barcode = catalog.barcode_from_text(query)
        if barcode:
            hit = await catalog.get_by_barcode(self.session, barcode)
            if hit is not None:
                products = [self._product(hit)]
                await self._attach_promotions(products)
                self.last_search = {
                    "products": products,
                    "fallback_without_discount": False,
                }
                return {
                    "ok": True,
                    "products": products,
                    "fallback_without_discount": False,
                    "exact_match": True,
                    "barcode_match": True,
                    "filters": {"query": query, "barcode": barcode},
                }
        if query:
            query = _clean_query(query) or query
            # Solo términos útiles: evita buscar frases encadenadas.
            query = catalog.clean_for_search(query) or query
            query = _normalize_tv_query(query)
        if category and TV_INTENT_RE.search(category):
            category = None
        state = await self._current_state()
        query_category = bool(query and SEARCH_RE.search(query))
        if not ignore_state:
            if not category and state.category and not query_category:
                category = state.category
            if not brand and state.brand and not query_category:
                brand = state.brand
        size = size or _requested_size(query or "") or (
            state.size if not ignore_state else None
        )
        has_filters = any(
            (
                category,
                brand,
                min_price is not None,
                max_price is not None,
                only_discount,
            )
        )
        if has_filters or not query:
            rows = await catalog.search_items(
                self.session,
                query,
                limit=take,
                category=category,
                brand=brand,
                min_price=min_price,
                max_price=max_price,
                only_discount=only_discount,
            )
        else:
            rows = await self._search_with_hot_cache(query, take)
        if not rows and category and query:
            # El cliente pudo cambiar de rubro ("ahora quiero alfombras"):
            # se prueba sin la categoría que venía arrastrando la charla.
            rows = await catalog.search_items(
                self.session,
                query,
                limit=take,
                brand=brand,
                min_price=min_price,
                max_price=max_price,
                only_discount=only_discount,
            )
            if rows:
                category = None
        fallback = False
        if not rows and only_discount:
            rows = await catalog.search_items(
                self.session,
                query,
                limit=min(int(limit or 5), 8),
                category=category,
                brand=brand,
                min_price=min_price,
                max_price=max_price,
                only_discount=False,
            )
            fallback = True
        products = [self._product(row) for row in rows]
        await self._attach_promotions(products)
        exact_match = any(
            catalog.is_head_match(row, query) for row in rows
        )
        # Si hay coincidencias reales por nombre, no mezclar accesorios
        # ("panel de TV", "soporte de TV") entre los primeros resultados.
        if exact_match and query and not has_filters:
            head_rows = [
                row for row in rows if catalog.is_head_match(row, query)
            ]
            if head_rows:
                rows = head_rows
                products = [self._product(row) for row in rows]
                await self._attach_promotions(products)
        # "colchón queen" sin coincidencias exactas: mejor mostrar colchones
        # (el producto base) que protectores que sólo mencionan la palabra.
        if rows and not exact_match and query and not has_filters:
            head = catalog.primary_term(query)
            if head and head.lower() != query.strip().lower():
                head_rows = await catalog.search_items(
                    self.session, head, limit=take
                )
                head_rows = [
                    row for row in head_rows if catalog.is_head_match(row, head)
                ]
                if head_rows:
                    rows = head_rows
                    products = [self._product(row) for row in rows]
                    await self._attach_promotions(products)
        # Precio y stock de los primeros resultados, en vivo desde SAP.
        await self._refresh_live_prices(products)
        # Si SAP dice que no hay stock, no se ofrece (salvo que no quede nada).
        if products and any(p.get("stock", 0) > 0 for p in products):
            products = [p for p in products if p.get("stock", 0) > 0]
        if not products and query:
            # Consulta sin resultados: se guarda para detectar huecos reales.
            await funnel.track_and_commit(
                self.session,
                "search_miss",
                contact_id=self.contact_id,
                query=query,
            )
        # El modelo puede pasar la medida aparte (size); si no viene, se toma
        # del texto de la búsqueda.
        size = (size or "").strip() or _requested_size(query or "")
        if size:
            size_re = re.compile(rf"\b{re.escape(size)}\b")
            products = [
                p
                for p in products
                if size_re.search(str(p.get("name") or ""))
            ]
            exact_match = bool(products)
        requested_quantity = max(1, int(quantity or 1))
        shortfall = 0
        if requested_quantity > 1:
            enough = [
                product
                for product in products
                if int(product.get("stock") or 0) >= requested_quantity
            ]
            if enough:
                products = enough
            else:
                products = []
                shortfall = requested_quantity
        if query and TV_INTENT_RE.search(query):
            products = _only_tvs(products)
        # Guard de coherencia: si la charla viene de un rubro y el cliente no
        # nombró otro, no se muestran resultados de otra categoría (evita que
        # "el precio más bajo" traiga alfombras).
        if products and query:
            estado_previo = await self._current_state()
            rubro = (getattr(estado_previo, "category", None) or "").strip()
            if rubro:
                del_rubro = [
                    p
                    for p in products
                    if rules_engine.same_category(rubro, p.get("category") or "")
                ]
                if del_rubro:
                    products = del_rubro
                elif not _nombra_producto(query, products):
                    products = []
        rules = await rules_engine.brand_rules(
            self.session, category=category or query
        )
        products = rules_engine.order_products(products, rules)
        promo_rules = await rules_engine.promotion_rules(
            self.session, any_category=True
        )
        products = rules_engine.order_promotions(products, promo_rules)
        # Se recuerda siempre la última búsqueda con resultados: sirve para
        # "mostrame las más vendidas" sin que el cliente repita el rubro.
        if query and products:
            await self._remember_search_context(query)
        state_brand = brand
        if not state_brand and products:
            candidate = products[0].get("brand")
            if candidate and _fold_word(candidate) in _fold_word(query or ""):
                state_brand = candidate
        await self._update_state(
            category=category or (
                catalog.primary_term(query) if query_category else None
            ),
            brand=state_brand,
            size=size,
            intent="search",
            last_sku=(products[0]["sku"] if products else None),
        )
        await recommendations.save(
            self.session,
            self.contact_id,
            query=query,
            category=category,
            brand=brand,
            size=size,
            min_price=min_price,
            max_price=max_price,
            products=products,
        )
        self.last_search = {
            "products": products,
            "fallback_without_discount": fallback,
        }
        return {
            "ok": True,
            "products": products,
            "fallback_without_discount": fallback,
            "exact_match": exact_match,
            "suggestion_hint": None
            if exact_match or not products
            else (
                "Ningún artículo coincide exactamente con lo pedido: son "
                "opciones relacionadas. Aclaralo y ofrecé alternativas."
            ),
            "filters": {
                "query": query,
                "category": category,
                "brand": brand,
                "min_price": min_price,
                "max_price": max_price,
                "quantity": requested_quantity,
                "only_discount": only_discount,
            },
            "quantity_shortfall": shortfall,
        }

    async def tool_get_catalog_facets(self, query: str) -> dict:
        await self._remember_search_context(query)
        await self._update_state(category=query, intent="availability")
        data = await catalog.facets(self.session, query, limit=5)
        rules = await rules_engine.brand_rules(
            self.session, category=query
        )
        brands = rules_engine.order_brands(data.get("brands", []), rules)
        return {
            "ok": True,
            "query": query,
            "total": data.get("total", 0),
            "brands": brands,
            "sizes": data.get("sizes", []),
        }

    async def tool_show_catalog(
        self,
        query: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        size: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        only_discount: bool = False,
        quantity: int = 1,
        limit: int = 5,
    ) -> dict:
        rows = await catalog.search_items(
            self.session,
            query,
            limit=min(int(limit or 5), 8),
            category=category,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            only_discount=only_discount,
        )
        fallback = False
        if not rows and only_discount:
            rows = await catalog.search_items(
                self.session,
                query,
                limit=min(int(limit or 5), 8),
                category=category,
                brand=brand,
                min_price=min_price,
                max_price=max_price,
                only_discount=False,
            )
            fallback = True
        products = [self._product(row) for row in rows]
        await self._attach_promotions(products)
        if size:
            size_re = re.compile(rf"\b{re.escape(str(size))}\b")
            products = [
                p
                for p in products
                if size_re.search(str(p.get("name") or ""))
            ]
        if quantity and int(quantity) > 1:
            products = [
                p
                for p in products
                if int(p.get("stock") or 0) >= int(quantity)
            ]
        rules = await rules_engine.brand_rules(
            self.session, category=category or query
        )
        products = rules_engine.order_products(products, rules)
        promo_rules = await rules_engine.promotion_rules(
            self.session, any_category=True
        )
        products = rules_engine.order_promotions(products, promo_rules)
        await self._update_state(
            category=category or query,
            brand=brand,
            size=size,
            intent="catalog",
        )
        if not native_commerce.is_ready():
            return {
                "ok": True,
                "native": False,
                "products": products,
                "fallback_without_discount": fallback,
                "note": (
                    "El catálogo nativo no está activo; usá los productos "
                    "para responder en texto."
                ),
            }
        if not products:
            return {
                "ok": True,
                "native": True,
                "count": 0,
                "fallback_without_discount": fallback,
                "note": "No hay productos con esos filtros.",
            }
        sections = [
            {
                "title": "Resultados",
                "product_items": [
                    {"product_retailer_id": product["sku"]}
                    for product in products
                ],
            }
        ]
        self.last_catalog = {
            "kind": "product" if len(products) == 1 else "product_list",
            "text": (
                "Estos son los productos que encontré para vos:"
            ),
            "sections": sections,
            "product_retailer_id": products[0]["sku"],
        }
        return {
            "ok": True,
            "native": True,
            "count": len(products),
            "fallback_without_discount": fallback,
            "message": "Catálogo filtrado listo para enviar.",
        }

    async def tool_get_product(self, sku: str, quantity: int = 1) -> dict:
        offer = await pricing.get_offer(
            self.session,
            sku,
            quantity=max(int(quantity or 1), 1),
        )
        if offer is None:
            return {"ok": False, "error": "SKU no encontrado"}
        data = offer.as_dict()
        row = await catalog.get_item(self.session, sku)
        if row is not None:
            data["brand"] = row.brand
            data["category"] = row.category
            data["barcode"] = row.barcode
            data["attributes"] = row.attributes or {}
        return {"ok": True, "product": data}

    async def tool_compare_products(self, sku_a: str, sku_b: str) -> dict:
        first = await self.tool_get_product(sku_a)
        second = await self.tool_get_product(sku_b)
        if not first.get("ok") or not second.get("ok"):
            return {
                "ok": False,
                "error": "No encontré uno de los dos artículos.",
            }

        def row(product: dict) -> dict:
            attrs = product.get("attributes") or {}
            return {
                "sku": product["sku"],
                "name": product["name"],
                "brand": product.get("brand"),
                "price": product["final_price"],
                "list_price": product["base_price"],
                "stock": sum(
                    (product.get("stock_by_store") or {}).values()
                ),
                "model": attrs.get("model"),
                "weight_kg": attrs.get("weight_kg"),
                "tiers": product.get("tiers") or [],
                "barcode": product.get("barcode"),
            }

        a = row(first["product"])
        b = row(second["product"])
        diff = Decimal(b["price"]) - Decimal(a["price"])
        cheaper = a["sku"] if diff > 0 else (b["sku"] if diff < 0 else None)
        return {
            "ok": True,
            "a": a,
            "b": b,
            "price_diff": str(diff),
            "cheaper": cheaper,
        }

    async def tool_identify_customer(
        self, document: str, consent: bool = False
    ) -> dict:
        if not consent:
            return {
                "ok": False,
                "error": "Necesitas consentimiento para buscar al cliente.",
            }
        sap = None
        try:
            if settings.sap_mode == "vtex":
                sap = get_sap(self.session)
                candidates = await vtex_customers.find_candidates(
                    sap, document
                )
            else:
                sap = ServiceLayerSap(self.session)
                candidates = await customers.find_by_document(sap, document)
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo identificar al cliente")
            return {"ok": False, "error": str(exc)[:300]}
        finally:
            if sap is not None:
                await sap.close()
            await customers.redact_document(
                self.session, self.contact_id, document
            )
        await customers.save_candidates(
            self.session, self.contact_id, candidates
        )
        return {
            "ok": True,
            "count": len(candidates),
            "candidates": candidates,
            "note": (
                "Confirmá el nombre con el cliente antes de vincular."
                if candidates
                else "No se encontró un cliente con ese documento."
            ),
        }

    async def tool_link_customer(
        self,
        card_code: str,
        consent: bool = False,
        document: str | None = None,
    ) -> dict:
        if not consent:
            return {
                "ok": False,
                "error": "Necesitas consentimiento para vincular al cliente.",
            }
        try:
            return await customers.link_customer(
                self.session,
                self.contact,
                card_code,
                document=document,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("No se pudo vincular al cliente")
            return {"ok": False, "error": str(exc)[:300]}

    async def tool_get_purchase_history(self, limit: int = 10) -> dict:
        result = await purchases.get_history(
            self.session, self.contact_id, limit=limit
        )
        result["linked"] = bool(
            self.contact.tax_id or self.contact.sap_card_code
        )
        return result

    async def tool_recommend_for_customer(
        self, need: str | None = None, limit: int = 3
    ) -> dict:
        return await purchases.recommend_for_customer(
            self.session,
            self.contact_id,
            need=need,
            limit=limit,
        )

    async def tool_get_best_sellers(
        self,
        category: str | None = None,
        limit: int = 5,
        query: str | None = None,
    ) -> dict:
        """Más vendidos acotados al rubro que viene mirando el cliente.

        Si no hay ventas de ese rubro devuelve vacío: "las licuadoras más
        vendidas" no puede responder con brochas.
        """
        referencia = (query or "").strip()
        if not referencia:
            try:
                conversacion = await self.session.scalar(
                    select(Conversation).where(
                        Conversation.contact_id == self.contact_id
                    )
                )
                referencia = (conversacion.last_query or "") if conversacion else ""
            except Exception:  # noqa: BLE001 - sin contexto se sigue igual
                referencia = ""

        if not category and referencia:
            category = catalog.primary_term(referencia)
        if not category:
            try:
                state = await self._current_state()
                category = state.category
            except Exception:  # noqa: BLE001
                category = None

        products = await sales_stats.best_sellers(
            self.session, category=category, limit=limit
        )
        if not products and referencia:
            # El rubro del cliente no siempre coincide con el nombre de la
            # categoría: se filtra por texto sobre un ranking amplio.
            term = referencia.lower().strip()
            amplio = await sales_stats.best_sellers(
                self.session, category=None, limit=max(limit * 4, 16)
            )
            products = [
                p
                for p in amplio
                if term
                and term in f"{p.get('name', '')} {p.get('category', '')}".lower()
            ][:limit]
        if not products and not category and not referencia:
            products = await sales_stats.best_sellers(
                self.session, category=None, limit=limit
            )
        return {
            "ok": True,
            "products": products,
            "category": category,
            "note": None
            if products
            else "No hay estadísticas de ventas de ese rubro; no mezcles categorías.",
        }

    async def tool_search_knowledge(self, query: str) -> dict:
        articles = knowledge.search(query, limit=3)
        return {
            "ok": True,
            "articles": articles,
            "note": (
                "Resumí en 3 a 6 líneas lo que responde a la pregunta; no "
                "copies el documento ni sus títulos."
            )
            if articles
            else (
                "No hay información publicada sobre eso. No inventes; "
                "ofrecé derivar con un asesor."
            ),
        }

    async def tool_record_feedback(
        self,
        type: str,
        consent: bool = False,
        rating: int | None = None,
        comment: str | None = None,
        order_number: str | None = None,
        sku: str | None = None,
    ) -> dict:
        try:
            return await feedback.record_feedback(
                self.session,
                self.contact_id,
                type=type,
                rating=rating,
                comment=comment,
                order_number=order_number,
                sku=sku,
                consent=consent,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    async def tool_skip_feedback(
        self, order_number: str | None = None
    ) -> dict:
        return await feedback.skip_feedback(
            self.session, self.contact_id, order_number=order_number
        )

    async def tool_get_feedback_summary(self, sku: str | None = None) -> dict:
        return {
            "ok": True,
            "summary": await feedback.feedback_summary(
                self.session, sku=sku
            ),
        }

    async def tool_get_customer_analysis(self) -> dict:
        analysis = await customer_analysis.analyze_customer(
            self.session, self.contact_id
        )
        return {"ok": True, "analysis": analysis}

    async def tool_get_customer_profile(self) -> dict:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.contact_id == self.contact_id
            )
        )
        conversation_id = conversation.id if conversation else ""
        profile = await memory_service.get_profile(
            self.session, self.contact_id
        )
        facts = await memory_service.get_facts(
            self.session, self.contact_id
        )
        purchase_summary = await purchases.history_summary(
            self.session, self.contact_id
        )
        analysis = await customer_analysis.analyze_customer(
            self.session, self.contact_id
        )
        text = await memory_service.memory_text(
            self.session, self.contact, conversation_id
        )
        return {
            "ok": True,
            "profile": {
                "name": self.contact.name,
                "city": profile.city if profile else None,
                "preferred_store": (
                    profile.preferred_store if profile else None
                ),
                "preferences": profile.preferences if profile else {},
                "consent": bool(profile and profile.consent_at),
            },
            "facts": [
                {"key": fact.key, "value": fact.value} for fact in facts
            ],
            "purchase_summary": purchase_summary,
            "analysis": analysis,
            "memory": text,
        }

    async def tool_remember_customer_fact(
        self, key: str, value: str, consent: bool = False
    ) -> dict:
        try:
            fact = await memory_service.remember_fact(
                self.session,
                self.contact_id,
                key,
                value,
                consent=consent,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "key": fact.key,
            "value": fact.value,
            "message": "Dato recordado para próximas conversaciones.",
        }

    async def tool_list_promotions(        self,
        category: str | None = None,
        limit: int = 5,
        min_discount: float = 0,
        min_price: float = 20,
    ) -> dict:
        today = date.today()
        stmt = (
            select(ProductPromotion, CatalogItem)
            .join(
                CatalogItem,
                CatalogItem.sku == ProductPromotion.sku,
            )
            .where(
                CatalogItem.active.is_(True),
                CatalogItem.stock > 0,
                or_(
                    ProductPromotion.valid_from.is_(None),
                    ProductPromotion.valid_from <= today,
                ),
                or_(
                    ProductPromotion.valid_to.is_(None),
                    ProductPromotion.valid_to >= today,
                ),
                ProductPromotion.tier_quantity.is_(None),
            )
        )
        if category:
            stmt = stmt.where(CatalogItem.category.ilike(f"%{category}%"))
        stmt = stmt.order_by(
            ProductPromotion.discount_percent.desc(),
            ProductPromotion.price.asc(),
        ).limit(300)
        rows = (await self.session.execute(stmt)).all()

        candidates = []
        seen: set[str] = set()
        for promo, item in rows:
            if promo.sku in seen or item.price <= 0 or promo.price <= 0:
                continue
            seen.add(promo.sku)
            if Decimal(item.price) < Decimal(str(min_price or 0)):
                continue
            discount = (
                (Decimal(item.price) - Decimal(promo.price))
                / Decimal(item.price)
                * 100
            ).quantize(Decimal("0.01"))
            if discount <= 0 or float(discount) < float(min_discount or 0):
                continue
            candidates.append(
                {
                    "sku": promo.sku,
                    "name": item.name,
                    "category": item.category,
                    "base_price": Decimal(item.price),
                    "final_price": Decimal(promo.price),
                    "discount_percent": discount,
                    "valid_from": promo.valid_from,
                    "valid_to": promo.valid_to,
                    "local_stock": item.stock,
                }
            )
        candidates.sort(
            key=lambda row: row["discount_percent"], reverse=True
        )

        # Diversificar categorías para no devolver 5 tornillos.
        selected = []
        used_categories: set[str] = set()
        for candidate in candidates:
            if len(selected) >= max(int(limit), 1):
                break
            category_key = (candidate["category"] or "").lower()
            if category_key and category_key in used_categories:
                continue
            selected.append(candidate)
            if category_key:
                used_categories.add(category_key)
        for candidate in candidates:
            if len(selected) >= max(int(limit), 1):
                break
            if candidate not in selected:
                selected.append(candidate)

        promotions = []
        for candidate in selected:
            promotions.append(
                {
                    "sku": candidate["sku"],
                    "name": candidate["name"],
                    "base_price": str(candidate["base_price"]),
                    "final_price": str(candidate["final_price"]),
                    "discount_percent": str(candidate["discount_percent"]),
                    "valid_from": (
                        candidate["valid_from"].isoformat()
                        if candidate["valid_from"]
                        else None
                    ),
                    "valid_to": (
                        candidate["valid_to"].isoformat()
                        if candidate["valid_to"]
                        else None
                    ),
                    "stock": candidate["local_stock"],
                    "stock_by_store": {},
                    "stores": [],
                }
            )

        return {
            "ok": True,
            "promotions": promotions,
            "note": None
            if promotions
            else "No hay promociones vigentes con stock en este momento.",
        }

    async def tool_add_to_cart(
        self, sku: str, quantity: int = 1, store: str | None = None
    ) -> dict:
        cart = await cart_service.get_or_create_cart(self.session, self.contact_id)
        try:
            await cart_service.add_item(
                self.session, cart, sku, int(quantity), store_code=store
            )
        except (cart_service.CartError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

        self.last_cart = True
        summary = await cart_service.summary(self.session, cart)
        line = next(
            (item for item in summary["items"] if item["sku"] == sku.strip().upper()),
            None,
        )
        return {
            "ok": True,
            "cart_total": str(summary["total"]),
            "items": len(summary["items"]),
            "count": summary["count"],
            "name": line["name"] if line else sku,
            "quantity": int(line["quantity"]) if line else int(quantity),
            "store_code": line["store_code"] if line else None,
            "store_name": line["store_name"] if line else None,
            "unit_price": str(line["unit_price"]) if line else None,
            "discount_percent": (
                str(line["discount_percent"]) if line else None
            ),
        }

    async def tool_remove_from_cart(self, sku: str) -> dict:
        cart = await cart_service.get_or_create_cart(
            self.session, self.contact_id
        )
        try:
            await cart_service.remove_item(self.session, cart, sku)
        except (cart_service.CartError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        summary = await cart_service.summary(self.session, cart)
        self.last_cart = True
        return {
            "ok": True,
            "removed": sku.strip().upper(),
            "items": len(summary["items"]),
            "total": str(summary["total"]),
        }

    async def tool_update_cart_quantity(
        self, sku: str, quantity: int
    ) -> dict:
        cart = await cart_service.get_or_create_cart(
            self.session, self.contact_id
        )
        try:
            await cart_service.set_quantity(
                self.session, cart, sku, int(quantity)
            )
        except (cart_service.CartError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        summary = await cart_service.summary(self.session, cart)
        self.last_cart = True
        return {
            "ok": True,
            "sku": sku.strip().upper(),
            "quantity": int(quantity),
            "items": len(summary["items"]),
            "total": str(summary["total"]),
        }

    async def tool_clear_cart(self) -> dict:
        cart = await cart_service.get_or_create_cart(
            self.session, self.contact_id
        )
        await cart_service.clear(self.session, cart)
        self.last_cart = True
        return {"ok": True, "items": 0, "total": "0"}

    async def tool_view_cart(self) -> dict:
        cart = await cart_service.get_or_create_cart(self.session, self.contact_id)
        self.last_cart = True
        summary = await cart_service.summary(self.session, cart)
        return {
            "ok": True,
            "items": [
                {
                    "sku": line["sku"],
                    "name": line["name"],
                    "quantity": line["quantity"],
                    "unit_price": str(line["unit_price"]),
                    "list_price": str(line["list_price"]),
                    "discount_percent": str(line["discount_percent"]),
                    "store_code": line["store_code"],
                    "store_name": line["store_name"],
                    "line_total": str(line["line_total"]),
                }
                for line in summary["items"]
            ],
            "total": str(summary["total"]),
            "currency": summary["currency"],
        }

    async def tool_checkout(self) -> dict:
        cart = await cart_service.get_or_create_cart(self.session, self.contact_id)
        try:
            order, payment = await orders.create_order(
                self.session, self.contact, cart, get_sap(self.session)
            )
        except (orders.CheckoutError, cart_service.CartError, SapError) as exc:
            await self.session.rollback()
            refreshed = await self.session.get(Contact, self.contact_id)
            if refreshed is not None:
                self.contact = refreshed
            # El intento cuenta en el embudo aunque el pedido no se cree.
            await funnel.track_and_commit(
                self.session,
                "checkout_start",
                contact_id=self.contact_id,
            )
            return {"ok": False, "error": str(exc)}
        await funnel.track_and_commit(
            self.session,
            "checkout_start",
            contact_id=self.contact_id,
            value=order.total,
        )
        self.last_checkout = {
            "order_number": order.number,
            "total": str(order.total),
            "payment_url": orders.payment_url(payment),
            "payment_id": payment.id,
        }
        return {"ok": True, **self.last_checkout}

    async def tool_order_status(self) -> dict:
        order = await orders.latest_order(self.session, self.contact_id)
        if order is None:
            return {"ok": False, "error": "No hay pedidos para este cliente"}
        label = {
            "pending_payment": "pendiente de pago",
            "paid": "pagado",
            "invoiced": "facturado",
            "cancelled": "cancelado",
        }.get(order.status, order.status)
        if order.status == "paid" and order.notes:
            label = "pagado, factura pendiente"
        return {
            "ok": True,
            "order_number": order.number,
            "status": order.status,
            "status_label": label,
            "total": str(order.total),
            "currency": order.currency,
            "invoice_doc_num": order.invoice_doc_num,
        }

    async def tool_explain_recommendation(self) -> dict:
        snapshot = await recommendations.latest(
            self.session, self.contact_id
        )
        if snapshot is None:
            return {
                "ok": False,
                "error": "No hay una recomendación reciente para explicar",
            }
        return {
            "ok": True,
            "explanation": recommendations.explain(snapshot),
            "products": snapshot.products or [],
        }

    async def tool_human_handoff(self, reason: str = "") -> dict:
        conversation = await self.session.scalar(
            select(Conversation).where(Conversation.contact_id == self.contact_id)
        )
        if conversation is None:
            return {"ok": False, "error": "Conversación no encontrada"}
        handoff, notification = await handoffs.create_handoff(
            self.session, conversation, self.contact, reason
        )
        return {
            "ok": True,
            "handoff_id": handoff.id,
            "message": "Conversación derivada a un asesor.",
            "notification": notification,
        }


PROMO_RE = re.compile(
    r"\b(promoci[oó]n(?:es)?|promo(?:s)?|descuento(?:s)?|oferta(?:s)?|rebaja(?:s)?)\b",
    re.IGNORECASE,
)
# Pedidos de recomendación: se precargan los más vendidos para ahorrar un
# turno del LLM (~2 s por turno).
RECO_RE = re.compile(
    r"\b(recomend\w*|recomiend\w*|suger\w*|sugerencia(?:s)?|aconsej\w*|"
    r"consejo(?:s)?)\b|"
    r"\bqu[eé]\s+me\s+conviene\b|\bpara\s+regalar\b",
    re.IGNORECASE,
)
EXPLAIN_RE = re.compile(
    r"\b(por\s*qu[eé]|porque|recomendaste|qu[eé]\s+tienen|"
    r"algo\s+especial|en\s+especial)\b",
    re.IGNORECASE,
)
RECOMMENDATION_EXPLAIN_RE = re.compile(
    r"\b(por\s*qu[eé]|porque)\b[\s\S]{0,90}\b"
    r"(recomend\w*|mostr\w*|opci\w*|esos|esas|eso|televisor\w*|producto)\b",
    re.IGNORECASE,
)
SEMANTIC_QUERY_RE = re.compile(
    r"\b(algo para|qu[eé] (tienen|hay) para|tienen para|"
    r"busco algo para|necesito algo para|regalo para|ideas para)\b",
    re.IGNORECASE,
)
# Consultas de políticas/FAQ: se precarga la base de conocimiento.
IDENTITY_RE = re.compile(
    r"\b(qui[eé]n (eres|sos|es)|c[oó]mo te llamas|c[oó]mo te llam[aá]s|"
    r"tu nombre|sos (un|una) (bot|robot|ia)|eres (un|una) (bot|robot|ia)|"
    r"qu[eé] (pod[eé]s|puedes) hacer|para qu[eé] serv[ií]s|"
    r"a qu[eé] te dedic[aá]s|sos real|eres real)\b",
    re.IGNORECASE,
)
FAREWELL_RE = re.compile(
    r"\b(hasta luego|hasta pronto|nos vemos|chau|chao|me despido|"
    r"eso es todo|nada m[aá]s|listo,? gracias|gracias,? hasta|"
    r"buenas noches,? gracias)\b",
    re.IGNORECASE,
)
WHY_RE = re.compile(
    r"\bpor ?qu[eé]\b[^.?!]{0,60}\b(recomend\w*|elegiste|elegí|ese|esa|eso|"
    r"este|esta|esos|esas|especial)\b|\bqu[eé] tiene de especial\b",
    re.IGNORECASE,
)
KNOWLEDGE_RE = re.compile(
    r"\b(pol[ií]tica(?:s)?|garant[ií]a(?:s)?|cambios?|devoluci[oó]n(?:es)?|"
    r"env[ií]os?|env[ií]o|delivery|entregas?|demoras?|tarda|plazos?|"
    r"horarios?|cuotas?|formas? de pago|facturaci[oó]n|"
    r"comprobante(?:s)?)\b",
    re.IGNORECASE,
)
# Respuestas cortas de aceptación: si el bot acaba de ofrecer el link de pago,
# cierran el pedido sin pasar por el LLM.
AFFIRMATIVE_RE = re.compile(
    r"^(si|sí|dale|ok|okey|de una|claro|obvio|perfecto|adelante|listo|va|"
    r"hagamoslo|hagámoslo|genera|generalo|general[oa]|sigamos)\b",
    re.IGNORECASE,
)
# Mensajes que no deben interpretarse como respuesta a una búsqueda previa.
_CONTROL_WORDS = {
    "hola",
    "buenas",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "menu",
    "inicio",
    "asesor",
    "humano",
    "gracias",
    "ok",
    "dale",
    "si",
    "sí",
    "no",
    "chau",
    "adios",
    "listo",
    "ayuda",
    "carrito",
}
CHECKOUT_RE = re.compile(
    r"\b(confirm(?:o|ar|a|á)|genera(?:r|me)?\s+(?:el\s+)?(?:qr|link)|"
    r"link\s+de\s+pago|pagar|checkout)\b",
    re.IGNORECASE,
)
PAYMENT_METHOD_RE = re.compile(
    r"\b(qr|tarjeta|efectivo|transferencia|cuotas?|"
    r"medios?\s+de\s+pago|formas?\s+de\s+pago)\b",
    re.IGNORECASE,
)
CLEAR_CART_RE = re.compile(
    r"\b(vac[ií]a(?:r|me)?|limpi(?:a|ar)|borr(?:a|ar))\b.*\bcarrito\b|"
    r"\bcarrito\b.*\b(vac[ií]a(?:r|me)?|limpi(?:a|ar)|borr(?:a|ar))\b",
    re.IGNORECASE,
)
# El estado del pedido se responde de forma determinista: si va al LLM, tiende
# a repetir el estado anterior de la conversación en vez de consultarlo.
STATUS_RE = re.compile(
    r"\b(estado|estatus|seguimiento)\b"
    r"|\b(c[oó]mo|como)\s+va\s+(el|mi)\s+(pedido|orden)\b"
    r"|\bmi\s+(pedido|orden|compra)\s+(ya|est[aá]|sali[oó]|lleg[oó]|fue|aparece)\b"
    r"|\bya\s+pagu[eé]\b"
    r"|\b(factura|comprobante)\b",
    re.IGNORECASE,
)
TRACKING_RE = re.compile(
    r"\b(seguimiento|tracking|rastre(?:ar|o)|gu[ií]a)\b"
    r"|\b(d[oó]nde\s+est[aá]|donde\s+esta)\s+(mi|el)\s+pedido\b"
    r"|\b(c[oó]mo|como)\s+va\s+(mi|el)\s+pedido\b"
    r"|\bestado\s+(de|del)\s+(mi\s+)?pedido\b"
    r"|\bmi\s+pedido\s+ya\b"
    r"|\b(n[uú]mero|id)\s+de\s+pedido\b"
    r"|\bquiero\s+(ver|saber)\s+(mi|el)\s+pedido\b",
    re.IGNORECASE,
)
PURCHASE_RE = re.compile(
    r"\b(mis\s+compras|mi\s+historial|historial\s+de\s+compras|"
    r"qu[eé]\s+compr[eé]|cu[aá]nto\s+gast[eé]|mis\s+pedidos)\b",
    re.IGNORECASE,
)
HANDOFF_RE = re.compile(
    r"\b(asesor|humano|persona\s+real|agente|hablar\s+con\s+alguien)\b",
    re.IGNORECASE,
)
COMPLAINT_RE = re.compile(
    r"\b(roto|rota|da[nñ]ado|defectuoso|no\s+funciona|reclamo|"
    r"devoluci[oó]n|devolver|cambiar\s+un\s+producto)\b",
    re.IGNORECASE,
)


DOCUMENTO_RE = re.compile(
    r"(?:\b(?:ci|nit|carnet|documento|doc)\b\s*(?:es|:)?\s*)"
    r"(\d{6,9}(?:-?\d{1,2})?)",
    re.IGNORECASE,
)
DOCUMENTO_SUELTO_RE = re.compile(r"^\s*(\d{6,9}(?:-\d{1,2})?)\s*$")


def _document_number(text: str) -> str | None:
    """CI o NIT en el mensaje: "mi CI es 4.567.890" o el número solo."""
    valor = (text or "").strip()
    # "4.567.890" y "4 567 890" son el mismo documento: se unen los dígitos.
    valor = re.sub(r"(?<=\d)[.\s](?=\d)", "", valor)
    con_texto = DOCUMENTO_RE.search(valor)
    if con_texto:
        return con_texto.group(1)
    suelto = DOCUMENTO_SUELTO_RE.match(valor)
    if suelto:
        return suelto.group(1)
    return None


# Preguntas sobre dueños o personal: el bot no tiene ese dato y no debe
# confundirlas con "quién sos".
# Pedido explícito de productos ("algo para X", "mostrame", "qué tenés").
PRODUCT_REQUEST_RE = re.compile(
    r"\b(algo para|que ten[eé]s|qu[eé] tienen|mostrame|mostr[aá]me|"
    r"buscame|buscar|quiero ver|opciones|ver productos)\b",
    re.IGNORECASE,
)
EMPRESA_PERSONA_RE = re.compile(
    r"\b(due[nñ]o|due[nñ]a|gerente|presidente|fundador|fundadora|"
    r"propietario|jefe|jefa|empleado|empleados|personal de la empresa)\b",
    re.IGNORECASE,
)


def _about_company_person(text: str) -> bool:
    return bool(EMPRESA_PERSONA_RE.search(text or ""))


PRECIO_BARATO_RE = re.compile(
    r"\b(m[aá]s\s+barat[oa]s?|m[aá]s\s+econ[oó]mic[oa]s?|"
    r"menor\s+precio|precio\s+m[aá]s\s+bajo|lo\s+m[aá]s\s+barato|"
    r"barat[oa]s?\s+que\s+haya|opci[oó]n\s+m[aá]s\s+barata)\b",
    re.IGNORECASE,
)
PRECIO_CARO_RE = re.compile(
    r"\b(m[aá]s\s+car[oa]s?|mayor\s+precio|precio\s+m[aá]s\s+alto|"
    r"lo\s+m[aá]s\s+caro)\b",
    re.IGNORECASE,
)


# Acciones que ya se resuelven con reglas: no hace falta interpretarlas.
_COMPREHENSION_SKIP_RE = re.compile(
    r"^\s*(agregar|a[ñn]adir|quitar|sacar|carrito|pagar|checkout|pedido|"
    r"tienes|tiene|tienen|hay|busco|buscame|mostrame|venden|vende|necesito|"
    r"menu|men[úu]|orden|seguimiento|\d+\s*$|s[íi]\s*$|no\s*$|ok\s*$|dale\s*$)",
    re.IGNORECASE,
)
def _nombra_producto(query: str, products: list[dict]) -> bool:
    """¿La consulta nombra alguno de los productos devueltos?

    Sirve para distinguir un cambio de tema real ("ahora quiero alfombras")
    de una consulta de modificador ("el más barato"), que debe quedarse en
    el rubro de la conversación.
    """
    terminos = catalog._relevance_terms(query)
    if not terminos:
        return False
    for producto in products:
        nombre = (producto.get("name") or "").lower()
        for termino in terminos:
            for variante in catalog._variants(termino):
                # Palabra completa: "mas" no debe coincidir con "Mashru".
                if re.search(rf"\b{re.escape(variante)}\b", nombre):
                    return True
    return False


# "¿Tienen juguetes?": se verifica en el catálogo antes de responder. El
# modelo tendía a decir "sí, tenemos" sin consultar.
DISPONIBILIDAD_RE = re.compile(
    r"^\s*(?:tienen|tiene|venden|vende|hay|manejan|maneja|"
    r"disponen de|cuentan con)\s+(.+)$",
    re.IGNORECASE,
)
# Temas de política: no son productos y no deben pasar por esta verificación.
_NO_ES_PRODUCTO = re.compile(
    r"\b(env[ií]o|env[ií]os|entrega|garant[ií]a|pago|pagos|cuotas?|"
    r"devoluci[oó]n|factura|cr[eé]dito|descuento|promoci[oó]n)\b",
    re.IGNORECASE,
)


def _idea_producto_valido(
    producto: dict, termino: str, idea: dict
) -> bool:
    """El producto debe nombrar el término y no ser otra cosa."""
    nombre = (producto.get("name") or "").lower()
    palabras = [parte for parte in termino.split() if len(parte) > 2]
    if palabras and not all(palabra in nombre for palabra in palabras):
        return False
    return not any(
        palabra in nombre for palabra in (idea.get("excluir") or ())
    )

def _pide_producto(text: str) -> bool:
    """¿El mensaje pide productos de forma explícita?"""
    return bool(PRODUCT_REQUEST_RE.search(text or ""))

def _availability_term(text: str) -> str | None:
    """Producto que el cliente pregunta si existe ("juguetes")."""
    valor = re.sub(r"^[¿¡\s]+", "", (text or "").strip())
    if _NO_ES_PRODUCTO.search(valor):
        return None
    match = DISPONIBILIDAD_RE.search(valor)
    if match is None:
        return None
    # "¿venden algo para halloween?" no es un producto: es una ocasión.
    if re.search(
        r"\b(algo|alg[uú]n|alguna|un|una|regalo|regalar|para)\b",
        match.group(1),
        re.IGNORECASE,
    ):
        return None
    resto = _clean_query(match.group(1))
    if len(resto) < 3:
        return None
    return resto


def _price_intent(text: str) -> str | None:
    """'asc' si pide lo más barato, 'desc' si pide lo más caro."""
    if PRECIO_BARATO_RE.search(text or ""):
        return "asc"
    if PRECIO_CARO_RE.search(text or ""):
        return "desc"
    return None


def _is_purchase_query(text: str) -> bool:
    """Solo historial explícito; "la lavadora que compré" no es "mis compras"."""
    folded = _fold_word(text)
    # Garantía, devolución o reclamo no piden identificación: se responden con
    # la política publicada o se derivan.
    if re.search(r"\b(garant[ií]a|devoluci[oó]n|reclamo)\b", folded) and not re.search(
        r"\b(mis\s+compras|mi\s+historial|mi\s+factura|mis\s+pedidos)\b", folded
    ):
        return False
    if PURCHASE_RE.search(text):
        return True
    if "factura" in folded:
        return True
    if re.search(r"\b(cu[aá]nto|total)\b.*\b(gast|compr)", folded):
        return True
    return bool(
        re.search(
            r"\b(mi\s+compra|mis\s+compras|mis\s+pedidos|"
            r"mi\s+historial|mi\s+factura)\b",
            folded,
        )
    )
FRIENDLY_CATEGORIES = [
    {"key": "sala", "label": "Sala y comedor", "category": "MUEBLES"},
    {"key": "dormitorio", "label": "Dormitorio", "category": "DECO HOGAR"},
    {"key": "bano", "label": "Baño", "category": "BAÑOS"},
    {"key": "cocina", "label": "Cocina", "category": "COCINAS"},
    {"key": "iluminacion", "label": "Iluminación", "category": "ILUMINACION"},
    {"key": "pintura", "label": "Pintura", "category": "PINTURA"},
    {"key": "ferreteria", "label": "Ferretería", "category": "FERRETERIA"},
    {"key": "jardin", "label": "Jardín", "category": "JARDIN"},
    {"key": "linea-blanca", "label": "Línea blanca", "category": "LINEA BLANCA"},
]
SEARCH_RE = re.compile(
    r"\b(living|sala|comedor|sofa|sill[oó]n|mesa|silla|aparador|rack|"
    r"colch[oó]n(?:es)?|cama(?:s)?|refri(?:gerador(?:es)?)?|"
    r"heladera(?:s)?|nevera(?:s)?|lavadora(?:s)?|"
    r"secadora(?:s)?|microondas|televisor(?:es)?|tv|l[aá]mpara(?:s)?|"
    r"foco(?:s)?|ducha(?:s)?|grifer[ií]a(?:s)?|pintura(?:s)?|"
    r"aire(?:s)?|acondicionador(?:es)?|acondicionado(?:s)?|split|"
    r"taladro(?:s)?|herramienta(?:s)?|maceta(?:s)?|jard[ií]n)\b",
    re.IGNORECASE,
)


class Agent:
    def __init__(self, wa: WhatsAppClient | None = None):
        self.wa = wa
        self._client: AsyncOpenAI | None = None
        # Camino que tomó la respuesta (para el panel y para depurar).
        self.trace: list[str] = []

    def _trace(self, note: str) -> None:
        if note not in self.trace:
            self.trace.append(note)

    def _llm(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
        return self._client

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        value = (value or "").strip()
        if len(value) <= limit:
            return value
        cut = value[: limit - 1].rstrip()
        if " " in cut:
            candidate = cut.rsplit(" ", 1)[0].rstrip()
            if len(candidate) >= 8:
                cut = candidate
        return cut + "…"

    async def _category_list(self, session: AsyncSession, contact: Contact) -> AgentReply:
        return AgentReply(
            [
                Outbound(
                    kind="list",
                    text=persona.categories_intro(),
                    button_text="Ver categorías",
                    sections=[
                        {
                            "title": "Ambientes y proyectos",
                            "rows": [
                                {
                                    "id": f"cat:{row['key']}",
                                    "title": self._truncate(row["label"], 24),
                                    "description": row["label"],
                                }
                                for row in FRIENDLY_CATEGORIES
                            ],
                        }
                    ],
                )
            ]
        )

    @staticmethod
    def _search_buttons() -> list[dict]:
        return [
            {"id": "more", "title": "Ver más"},
            {"id": "filter", "title": "Filtrar"},
            {"id": "human", "title": "Asesor"},
        ]

    async def _remember_query(
        self, session: AsyncSession, contact: Contact, query: str
    ) -> None:
        conversation = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contact.id)
        )
        if conversation is None:
            conversation = Conversation(contact_id=contact.id)
            session.add(conversation)
        conversation.last_query = (query or "")[:300] or None
        await session.commit()

    async def _purchase_history_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        result = await Toolbox(session, contact, self.wa).tool_get_purchase_history(
            limit=5
        )
        summary = result.get("summary") or {}
        count = int(summary.get("count") or 0)
        if not count:
            return AgentReply(
                [
                    Outbound(
                        text=(
                            "No encontré compras registradas a tu nombre. "
                            "¿Querés que busquemos un producto o te derivo con "
                            "un asesor?"
                        )
                    )
                ]
            )
        total = money(summary.get("total") or 0)
        lines = [
            f"Tenés {count} compra{'s' if count != 1 else ''} por {total}."
        ]
        for purchase in (result.get("purchases") or [])[:3]:
            first = next(
                (
                    line.get("name")
                    for line in purchase.get("lines") or []
                    if line.get("name")
                ),
                "compra",
            )
            lines.append(
                f"• {purchase.get('date')}: {money(purchase.get('total') or 0)} "
                f"— {first}"
            )
        lines.append("¿Querés que te muestre el detalle de alguna?")
        return AgentReply([Outbound(text="\n".join(lines))])

    @staticmethod
    def _ambiguity_reply(event: dict | None) -> AgentReply:
        """La frase puede significar dos cosas: se pregunta antes de asumir."""
        terms = [term for term in ((event or {}).get("direct") or []) if term]
        buttons = [
            {"id": f"find:{term}", "title": term.title()[:20]}
            for term in terms[:2]
        ]
        buttons.append({"id": "human", "title": "Asesor"})
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Quiero mostrarte algo que te sirva. "
                        "¿Para qué lo necesitás exactamente?"
                    ),
                    buttons=buttons[:3],
                )
            ]
        )

    @staticmethod
    def _policy_reply(topic: str) -> AgentReply:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=policy_guard.reply(topic),
                    buttons=[
                        {"id": "human", "title": "Hablar con alguien"},
                        {"id": "catalog", "title": "Seguir con productos"},
                    ],
                )
            ]
        )

    async def _direct_reply_for_tool(
        self, session: AsyncSession, contact: Contact, call
    ) -> AgentReply | None:
        """Respuesta determinística cuando la herramienta pedida ya se sabe
        contestar, sin gastar una segunda llamada al modelo."""
        name = getattr(call.function, "name", "")
        if name not in ("search_products", "get_product"):
            return None
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except (ValueError, TypeError):
            return None
        if not isinstance(arguments, dict):
            return None

        try:
            if name == "get_product":
                sku = str(arguments.get("sku") or "").strip()
                if not sku:
                    return None
                return await self._product_detail(session, contact, sku)

            query = " ".join(
                str(arguments.get(key) or "")
                for key in ("query", "brand", "category", "size")
            ).strip()
            if arguments.get("only_discount"):
                query = f"{query} en descuento"
            if not query:
                return None
            limit = min(int(arguments.get("limit") or 5), 5)
            return await self._search_reply(
                session,
                contact,
                query,
                limit=limit,
                min_price=arguments.get("min_price"),
                max_price=arguments.get("max_price"),
            )
        except Exception:  # noqa: BLE001 - si falla, sigue el camino normal
            logger.exception("No se pudo responder directo; se sigue con el modelo")
            return None
    async def _frustration_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        """Cliente enojado o esperando: disculpa y derivación inmediata."""
        toolbox = Toolbox(session, contact, self.wa)
        try:
            await toolbox.tool_human_handoff(
                "Cliente enojado o esperando respuesta"
            )
        except Exception:  # noqa: BLE001 - la disculpa no se pierde
            logger.exception("No se pudo crear el handoff por frustración")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=persona.frustration(),
                    buttons=[{"id": "human", "title": "Hablar con alguien"}],
                )
            ]
        )

    @staticmethod
    def _empathy_reply(decision: dict) -> AgentReply:
        """Ante algo delicado: empatía, cero venta y una salida amable."""
        text = persona.empathy(
            decision.get("sensitive_topic"), closing=bool(decision.get("closing"))
        )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=text,
                    buttons=[
                        {"id": "human", "title": "Hablar con alguien"},
                        {"id": "catalog", "title": "Seguir con productos"},
                    ],
                )
            ]
        )

    @staticmethod
    def _personal_pivot() -> AgentReply:
        """El cliente contó algo personal: se reconoce sin empujar la venta."""
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Gracias por contarme.\n\n"
                        "Si querés retomamos con lo que estabas buscando, y si "
                        "preferís hablar con alguien del equipo, te paso."
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Seguir con productos"},
                        {"id": "human", "title": "Hablar con alguien"},
                    ],
                )
            ]
        )

    @staticmethod
    def _occasion_pivot(event: dict) -> AgentReply:
        """Reconoce el plan del cliente y ofrece algo concreto, sin inventar."""
        label = (event.get("label") or "").lower()
        terms = [term for term in (event.get("direct") or []) if term][:2]
        buttons = [
            {"id": f"find:{term}", "title": term.title()[:20]}
            for term in terms
        ]
        buttons.append({"id": "human", "title": "Asesor"})

        text = (
            f"Para *{label}* puedo mostrarte opciones concretas del catálogo.\n\n"
            "Decime qué estás buscando y te armo dos o tres alternativas."
        )
        return AgentReply(
            [Outbound(kind="buttons", text=text, buttons=buttons[:3])]
        )

    async def _image_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        media: dict,
    ) -> AgentReply | None:
        """Interpreta la imagen y ofrece productos parecidos del catálogo."""
        contenido = await media_service.download(media.get("media_id") or "")
        if contenido is None:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "Recibí tu imagen pero no pude abrirla. ¿Me contás "
                            "qué producto es y qué querés saber?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver productos"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        archivo, mime = contenido
        descripcion = await vision.describe(archivo, mime)
        if descripcion is None:
            self._trace("Imagen sin visión configurada")
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "Recibí tu imagen. Para buscarte algo igual o "
                            "parecido necesito que me digas qué producto es "
                            "(por ejemplo: taladro, licuadora, colchón).\n\n"
                            "¿Me lo escribís y te muestro opciones?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        objeto = descripcion.get("objeto") or ""
        categoria = descripcion.get("categoria") or ""
        marca = descripcion.get("marca") or ""
        atributos = descripcion.get("atributos") or ""
        if not objeto:
            self._trace("Imagen sin producto reconocible")
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "Miré la imagen pero no reconozco un producto en "
                            "ella. ¿Me contás qué estás buscando?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        consulta = " ".join(
            parte for parte in (objeto, marca, atributos) if parte
        )
        caja = Toolbox(session, contact, self.wa)
        resultado = await caja.tool_search_products(
            query=consulta, limit=3, ignore_state=True
        )
        productos = resultado.get("products") or []
        if productos:
            self._trace(f"Imagen: {objeto} con opciones")
            lead = (
                f"Veo que me enviaste una imagen: parece *{objeto}*"
                + (f" ({marca})" if marca else "")
                + ". En la tienda tenemos opciones parecidas:"
            )
            return AgentReply(
                [
                    Outbound(text=lead),
                    *self._search_cards(productos[:3]),
                    Outbound(
                        kind="buttons",
                        text="¿Te muestro el detalle de alguno o buscamos otra cosa?",
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    ),
                ]
            )

        # Sin coincidencia: se prueba por el rubro que detectó la visión.
        if categoria:
            rubro = await caja.tool_search_products(
                query=categoria, limit=3, ignore_state=True
            )
            productos = rubro.get("products") or []
        if productos:
            self._trace(f"Imagen: {objeto} sin igual, rubro {categoria}")
            return AgentReply(
                [
                    Outbound(
                        text=(
                            f"Veo que me enviaste una imagen: parece *{objeto}*"
                            + (f" ({marca})" if marca else "")
                            + f". No tengo ese modelo exacto, pero en "
                            f"*{categoria or objeto}* tengo esto:"
                        )
                    ),
                    *self._search_cards(productos[:3]),
                    Outbound(
                        kind="buttons",
                        text="¿Te interesa alguna o hablamos con un asesor?",
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    ),
                ]
            )

        self._trace(f"Imagen: {objeto} sin coincidencias")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        f"Veo que me enviaste una imagen: parece *{objeto}*"
                        + (f" ({marca})" if marca else "")
                        + ". No encontré algo igual en el catálogo ahora. "
                        "¿Querés que lo busque un asesor o te muestro otras "
                        "categorías?"
                    ),
                    buttons=[
                        {"id": "human", "title": "Asesor"},
                        {"id": "catalog", "title": "Ver categorías"},
                    ],
                )
            ]
        )

    async def _idea_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        intent: dict,
    ) -> AgentReply:
        """Responde una idea ("distraer a las visitas") con opciones reales."""
        toolbox = Toolbox(session, contact, self.wa)
        encontrados: list[dict] = []
        vistos: set[str] = set()
        frases: list[str] = []
        for idea in intent["ideas"]:
            for termino in idea["terminos"]:
                resultado = await toolbox.tool_search_products(
                    query=termino, limit=2, ignore_state=True
                )
                productos = [
                    item
                    for item in (resultado.get("products") or [])
                    if _idea_producto_valido(item, termino, idea)
                ]
                if not productos:
                    continue
                producto = productos[0]
                if producto["sku"] in vistos:
                    break
                vistos.add(producto["sku"])
                encontrados.append(producto)
                frases.append(idea["frase"])
                break
            if len(encontrados) >= 3:
                break
        if not encontrados:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            f"Para {intent['label']} no tengo algo puntual en "
                            "el catálogo ahora. Puedo mostrarte otras líneas o "
                            "pasarte con un asesor que te oriente."
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        encabezado = f"Para {intent['label']} te propongo:"
        detalle = "\n".join(f"• {frase}" for frase in frases)
        mensajes = [
            Outbound(text=f"{encabezado}\n\n{detalle}"),
            *self._search_cards(encontrados[:3]),
            Outbound(
                kind="buttons",
                text="¿Te muestro el detalle de alguno o buscamos otra cosa?",
                buttons=[
                    {"id": "catalog", "title": "Ver categorías"},
                    {"id": "human", "title": "Asesor"},
                ],
            ),
        ]
        return AgentReply(mensajes)

    async def _occasion_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        event: dict,
    ) -> AgentReply:
        if _is_personal_statement(text):
            return self._occasion_pivot(event)
        toolbox = Toolbox(session, contact, self.wa)
        direct: list[dict] = []
        seen: set[str] = set()
        for term in event["direct"]:
            result = await toolbox.tool_search_products(
                query=term, limit=1, ignore_state=True
            )
            for product in result.get("products") or []:
                if product["sku"] in seen:
                    continue
                if occasions.excluded(
                    product.get("name") or "",
                    event,
                    product.get("category"),
                ):
                    continue
                if not _semantic_term_match(product, term):
                    continue
                seen.add(product["sku"])
                direct.append(product)
            if len(direct) >= 3:
                break
        if direct:
            return AgentReply(
                [
                    Outbound(
                        text=(
                            f"Para *{event['label']}* te puedo ofrecer esto:"
                        )
                    ),
                    *self._search_cards(direct[:3]),
                    Outbound(
                        kind="buttons",
                        text=(
                            "¿Querés que busque algo más de la ocasión o "
                            "preferís ver otra categoría?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    ),
                ]
            )
        bridges = event.get("bridges") or []
        for bridge in bridges:
            bridge_products: list[dict] = []
            bridge_seen: set[str] = set()
            for term in bridge["terms"]:
                result = await toolbox.tool_search_products(
                    query=term, limit=2, ignore_state=True
                )
                for product in result.get("products") or []:
                    if product["sku"] in bridge_seen:
                        continue
                    bridge_seen.add(product["sku"])
                    bridge_products.append(product)
            if bridge_products:
                return AgentReply(
                    [
                        Outbound(
                            text=(
                                f"Lamentablemente no tengo productos para "
                                f"*{event['label']}*. Si te sirve, para "
                                f"*{bridge['label']}* tengo esto:"
                            )
                        ),
                        *self._search_cards(bridge_products[:2]),
                        Outbound(
                            kind="buttons",
                            text=(
                                "¿Te muestro más opciones para esa ocasión "
                                "o hablamos con un asesor?"
                            ),
                            buttons=[
                                {"id": "catalog", "title": "Ver categorías"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        ),
                    ]
                )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        f"Lamentablemente no tengo productos para "
                        f"*{event['label']}*. ¿Querés que veamos decoración, "
                        "otra categoría o te derivo con un asesor?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _human_fallback(
        self, session: AsyncSession, contact: Contact, reason: str
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        notification: dict = {}
        try:
            resultado = await toolbox.tool_human_handoff(reason[:200])
            notification = resultado.get("notification") or {}
        except Exception:  # noqa: BLE001 - no dejar sin respuesta
            logger.exception("No se pudo crear el handoff de aclaración")
        if notification.get("queued"):
            self._trace("Derivación en cola")
            texto = persona.handoff_queued(
                office_open=bool(notification.get("office_open", True))
            )
        else:
            texto = (
                "Para no darte una respuesta incorrecta, te derivo con un "
                "asesor. ¿Querés que siga con otra consulta mientras tanto?"
            )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=texto,
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _clarify_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        *,
        question: str,
        query: str,
        slot: str = "topic",
    ) -> AgentReply:
        # Se guarda el rubro limpio, no la frase entera: la respuesta del
        # cliente se combina con esto y no queremos oraciones encadenadas.
        base = _clean_query(query) or query
        await conversation_guard.set_pending(
            session,
            contact,
            slot=slot,
            question=question,
            query=base,
        )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=question,
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _semantic_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
    ) -> AgentReply | None:
        if not settings.deepseek_api_key:
            return None
        # Si el cliente nombró un producto con un atributo ("espejos
        # redondos"), la búsqueda literal manda: la expansión semántica
        # devolvía cuadrados porque ignora el atributo.
        literal = await Toolbox(
            session, contact, self.wa
        ).tool_search_products(query=text, limit=3)
        productos_literal = literal.get("products") or []
        terminos = catalog._relevance_terms(text)
        if productos_literal and terminos:
            variantes = catalog._variants(terminos[0])
            if any(
                variante in (producto.get("name") or "").lower()
                for producto in productos_literal
                for variante in variantes
            ):
                titulo = _clean_query(text) or text
                return AgentReply(
                    [
                        Outbound(
                            text=f"Para *{titulo}* tengo esto que puede servirte:"
                        ),
                        *self._search_cards(productos_literal),
                    ]
                )
        try:
            expansion = await semantic.expand(
                session, text, self._llm()
            )
        except Exception:  # noqa: BLE001 - nunca romper por enriquecimiento
            logger.exception("No se pudo expandir la consulta")
            return None
        if not expansion:
            return None
        topic = re.sub(
            r"^(?:(?:tienes|tienen|hay|busco|necesito|quiero|"
            r"me\s+interesa)\s+)?(?:algo\s+para|regalo\s+para|"
            r"ideas\s+para)\s*",
            "",
            (text or "").strip(),
            flags=re.IGNORECASE,
        )
        topic = re.sub(r"[?¿!]+", "", topic).strip() or "eso"
        # Para mostrar solo el rubro y la medida, no la frase entera.
        terminos = catalog._relevance_terms(topic)[:3]
        topic = " ".join(terminos) or topic
        exclusions = expansion.get("exclusions") or []
        toolbox = Toolbox(session, contact, self.wa)
        direct: list[dict] = []
        seen: set[str] = set()
        for term in expansion.get("related_terms") or []:
            result = await toolbox.tool_search_products(
                query=term, limit=3, ignore_state=True
            )
            for product in result.get("products") or []:
                if product["sku"] in seen:
                    continue
                blob = (
                    f"{product.get('name') or ''} "
                    f"{product.get('category') or ''}"
                ).lower()
                if any(item in blob for item in exclusions):
                    continue
                if not _semantic_term_match(product, term):
                    continue
                seen.add(product["sku"])
                direct.append(product)
            if len(direct) >= 3:
                break
        if direct:
            return AgentReply(
                [
                    Outbound(
                        text=f"Para *{topic}* tengo esto que puede servirte:"
                    ),
                    *self._search_cards(direct[:3]),
                    Outbound(
                        kind="buttons",
                        text=(
                            "¿Querés que busque otra cosa o te muestro "
                            "categorías relacionadas?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    ),
                ]
            )
        adjacent: list[dict] = []
        seen.clear()
        for term in expansion.get("adjacent_terms") or []:
            result = await toolbox.tool_search_products(
                query=term, limit=2, ignore_state=True
            )
            for product in result.get("products") or []:
                if product["sku"] in seen:
                    continue
                if not _semantic_term_match(product, term):
                    continue
                seen.add(product["sku"])
                adjacent.append(product)
        if adjacent:
            return AgentReply(
                [
                    Outbound(
                        text=(
                            f"No tengo productos específicos para "
                            f"*{topic}*. Si te sirve, tengo esto "
                            "como alternativa:"
                        )
                    ),
                    *self._search_cards(adjacent[:2]),
                    Outbound(
                        kind="buttons",
                        text=(
                            "¿Te muestro más opciones o hablamos con un "
                            "asesor?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    ),
                ]
            )
        return None

    async def _search_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        query: str,
        *,
        limit: int = 5,
        min_price: float | None = None,
        max_price: float | None = None,
        quantity: int | None = None,
        policy: rule_policy.RulePolicy | None = None,
    ) -> AgentReply:
        self._trace("Búsqueda en catálogo")
        # Referencias y atributos ("ese", "de 13mm", "con luz"): si la frase es
        # corta y ya hay rubro en la charla, el modelo la reescribe antes de
        # buscar. Así no se pierde el hilo ni se buscan palabras sueltas.
        if (
            query
            and settings.deepseek_api_key
            and settings.understanding_enabled
            and len(query.split()) <= 5
        ):
            try:
                estado_actual = await self._current_state()
                rubro = (getattr(estado_actual, "category", None) or "").strip()
                if rubro and not _nombra_producto(query, [{"name": rubro}]):
                    entendido = await understanding.parse(self._llm(), query)
                    producto = (entendido or {}).get("producto")
                    atributos = (entendido or {}).get("atributos") or []
                    if producto:
                        query = " ".join([producto, *atributos]).strip()
                        self._trace(f"Consulta reinterpretada: {query}")
                    elif atributos:
                        query = " ".join([rubro, *atributos]).strip()
                        self._trace(f"Consulta ampliada: {query}")
            except Exception:  # noqa: BLE001 - interpretar no debe romper
                logger.debug("No se pudo reinterpretar la búsqueda", exc_info=True)
        # Si el cliente ya dijo la medida, la búsqueda la usa sin volver a
        # preguntarla (memoria de preferencias).
        try:
            query = preferences.enrich(
                query, await preferences.known(session, contact)
            )
        except Exception:  # noqa: BLE001 - la memoria no bloquea la búsqueda
            logger.debug("No se pudo leer preferencias", exc_info=True)
        original_query = query
        quantity = quantity or _requested_quantity(original_query)
        if min_price is None and max_price is None:
            budget_min, budget_max = _requested_budget(original_query)
            min_price, max_price = budget_min, budget_max
        cleaned_query = (
            _strip_budget(original_query)
            if min_price is not None or max_price is not None
            else original_query
        )
        if quantity > 1:
            cleaned_query = _strip_quantity(cleaned_query, quantity) or cleaned_query
        query = _clean_query(cleaned_query) or cleaned_query
        query = _normalize_tv_query(query)
        await self._remember_query(session, contact, query)
        # Pedido amplio ("colchón"): preguntar medida/marca antes de listar.
        # Mostrar todo el catálogo es tarea del ecommerce, no del chat.
        if (
            catalog.is_broad_query(query)
            and min_price is None
            and max_price is None
        ):
            info = await catalog.facets(session, query, limit=3)
            options = (
                info["sizes"][:3] if info["sizes"] else info["brands"][:3]
            )
            total = int(info.get("total") or 0)
            if total and options:
                plural = "opciones" if total != 1 else "opción"
                if info["sizes"]:
                    text = (
                        f"Tenemos {total} {plural} de {query} en medidas:\n"
                        f"{_numbered_lines(info['sizes'][:3])}\n\n"
                        "¿Qué medida te sirve?"
                    )
                else:
                    text = (
                        f"Tenemos {total} {plural} de {query}:\n"
                        f"{_numbered_lines(info['brands'][:3])}\n\n"
                        "¿Alguna marca en particular o te muestro las más "
                        "elegidas?"
                    )
                return AgentReply(
                    [
                        Outbound(
                            kind="buttons",
                            text=text,
                            buttons=[
                                {
                                    "id": f"refine:{option}",
                                    "title": self._truncate(option, 20),
                                }
                                for option in options[:3]
                            ],
                        )
                    ]
                )

        toolbox = Toolbox(session, contact, self.wa)
        # Si el cliente cambia de rubro, no se arrastran marca ni medida de la
        # búsqueda anterior.
        ignore_state = False
        term = catalog.primary_term(query)
        if term:
            try:
                conversation = await session.scalar(
                    select(Conversation).where(
                        Conversation.contact_id == contact.id
                    )
                )
                if conversation is not None:
                    estado = await conversation_state.get_state(
                        session, conversation.id
                    )
                    if estado.category and _fold_word(
                        estado.category
                    ) != _fold_word(term):
                        ignore_state = True
                        self._trace(f"Cambio de rubro: {term}")
            except Exception:  # noqa: BLE001 - no frenar la búsqueda
                logger.debug("No se pudo comparar el rubro", exc_info=True)
        result = await toolbox.tool_search_products(
            query=query,
            limit=min(int(limit), 5),
            min_price=min_price,
            max_price=max_price,
            quantity=quantity,
            ignore_state=ignore_state,
        )
        # Si ese término ya se resolvió antes, se usa la consulta aprendida.
        consulta_original = query
        aprendida = await learning.recall(session, consulta_original)
        if aprendida and aprendida != query:
            result = await toolbox.tool_search_products(
                query=aprendida,
                limit=min(int(limit), 5),
                min_price=min_price,
                max_price=max_price,
                quantity=quantity,
                ignore_state=True,
            )
            if result.get("products"):
                query = aprendida
                self._trace(f"Consulta aprendida: {aprendida}")

        products = result.get("products") or []
        if not products:
            # Relajación: si la frase trae un término que no existe ("oled"),
            # se van quitando los últimos términos hasta encontrar algo.
            terminos = catalog.clean_for_search(query).split()
            for corte in range(len(terminos) - 1, 0, -1):
                parcial = " ".join(terminos[:corte])
                retry = await toolbox.tool_search_products(
                    query=parcial,
                    limit=min(int(limit), 5),
                    min_price=min_price,
                    max_price=max_price,
                    quantity=quantity,
                    ignore_state=True,
                )
                if retry.get("products"):
                    products = retry["products"]
                    result = retry
                    if parcial.lower() != (query or "").strip().lower():
                        self._trace(f"Consulta relajada: {parcial}")
                    query = parcial
                    break
        if not products and settings.deepseek_api_key:
            # Última red: el modelo interpreta el término y se reintenta con
            # producto + atributos. Si funciona, queda aprendido.
            entendido = None
            try:
                entendido = await understanding.parse(self._llm(), consulta_original)
            except Exception:  # noqa: BLE001 - interpretar no debe romper
                entendido = None
            producto = (entendido or {}).get("producto")
            atributos = (entendido or {}).get("atributos") or []
            candidato = " ".join([producto, *atributos]).strip() if producto else ""
            if candidato and candidato.lower() != (query or "").lower():
                retry = await toolbox.tool_search_products(
                    query=candidato,
                    limit=min(int(limit), 5),
                    min_price=min_price,
                    max_price=max_price,
                    quantity=quantity,
                    ignore_state=True,
                )
                if retry.get("products"):
                    products = retry["products"]
                    result = retry
                    query = candidato
                    self._trace(f"Consulta reinterpretada: {candidato}")
                    await learning.remember(
                        session,
                        term=consulta_original,
                        query=candidato,
                        producto=producto,
                        atributos=atributos,
                    )

        if not products:
            await learning.record_miss(session, consulta_original)
            if result.get("quantity_shortfall"):
                qty = result["quantity_shortfall"]
                return AgentReply(
                    [
                        Outbound(
                            kind="buttons",
                            text=(
                                f"No tengo {qty} unidades disponibles de "
                                "*{_clean_query(query)}* en este momento. "
                                "¿Querés que busque de a una o ver otra "
                                "categoría?"
                            ),
                            buttons=[
                                {"id": "search", "title": "Buscar otra cosa"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        )
                    ]
                )
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            f"No tengo nada para *{query.strip()}* en este "
                            "momento. Trabajo con línea blanca, colchones, "
                            "muebles, iluminación, baño y ferretería. "
                            "¿Te muestro alguna categoría o buscamos de otra "
                            "forma?"
                        ),
                        buttons=[
                            {"id": "search", "title": "Buscar otra cosa"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        products = result.get("products") or []
        # Se guarda qué producto se mostró primero: sirve para explicar luego
        # "¿por qué me recomendaste ese?".
        await funnel.track(
            session,
            "search",
            contact=contact,
            query=query,
            sku=products[0]["sku"] if products else None,
        )
        if len(products) == 1:
            only = products[0]
            intro = (
                f"Me queda disponible esta opción: *{only['name']}*."
                if result.get("exact_match", True)
                else (
                    f"No tengo *{_clean_query(query)}* exactamente, pero "
                    f"tengo esta parecida: *{only['name']}*."
                )
            )
        else:
            intro = (
                persona.search_intro()
                if result.get("exact_match", True)
                else (
                    f"No tengo *{_clean_query(query)}* exactamente, pero tengo "
                    "estas opciones parecidas:"
                )
            )
        return AgentReply(
            [
                Outbound(text=intro),
                *self._search_cards(products),
            ]
        )

    async def _product_list(
        self,
        session: AsyncSession,
        contact: Contact,
        category: str,
    ) -> AgentReply:
        key = category.strip().lower()
        friendly = next(
            (row for row in FRIENDLY_CATEGORIES if row["key"] == key),
            None,
        )
        canonical = friendly["category"] if friendly else category
        label = friendly["label"] if friendly else category
        toolbox = Toolbox(session, contact, self.wa)
        result = await toolbox.tool_search_products(
            category=canonical, limit=5
        )
        products = result.get("products") or []
        if not products:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            f"No encontré disponibilidad en {label}. "
                            "¿Querés ver otra categoría?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        sections = [
            {
                "title": self._truncate(label, 24),
                "rows": [
                    {
                        "id": f"product:{product['sku']}",
                        "title": self._truncate(product["name"], 24),
                        "description": (
                            f"Bs {product.get('promo_price') or product['price']}"
                            + (
                                f" · {product['brand']}"
                                if product.get("brand")
                                else ""
                            )
                        )[:72],
                    }
                    for product in products[:9]
                ],
            }
        ]
        return AgentReply(
            [
                Outbound(
                    kind="list",
                    text=f"Opciones en {label}:",
                    button_text="Ver productos",
                    sections=sections,
                )
            ]
        )

    async def _product_detail(
        self, session: AsyncSession, contact: Contact, sku: str
    ) -> AgentReply:
        self._trace("Ficha de producto")
        toolbox = Toolbox(session, contact, self.wa)
        result = await toolbox.tool_get_product(sku)
        if not result.get("ok"):
            return AgentReply(
                [
                    Outbound(
                        text="No encontré ese producto. ¿Querés ver otra opción?"),
                ]
            )
        product = result["product"]
        await funnel.track(
            session, "product_view", contact=contact, sku=product.get("sku")
        )
        stock = sum((product.get("stock_by_store") or {}).values())
        base = Decimal(
            product.get("base_price") or product.get("final_price") or 0
        )
        final = Decimal(product.get("final_price") or base)
        discount = str(product.get("discount_percent") or "0")
        lines = [f"*{product['name']}*"]
        if product.get("brand"):
            lines.append(f"Marca: {product['brand']}")
        if product.get("is_promotion"):
            lines.extend(
                [
                    f"Precio de lista: Bs {base:,.2f}",
                    f"Precio con descuento: *Bs {final:,.2f}*",
                    f"Descuento: {discount}%",
                ]
            )
        elif product.get("is_special_price"):
            lines.extend(
                [
                    f"Precio de lista: Bs {base:,.2f}",
                    f"Precio especial vigente: *Bs {final:,.2f}*",
                ]
            )
        else:
            lines.append(f"Precio: *Bs {final:,.2f}*")
        if product.get("period_to"):
            lines.append(f"Vigente hasta {product['period_to']}")
        for tier in product.get("tiers") or []:
            if tier.get("quantity") and tier.get("price"):
                lines.append(
                    f"Por {tier['quantity']} unidades: Bs {tier['price']} c/u"
                )
        attrs = product.get("attributes") or {}
        if product.get("category"):
            lines.append(f"Categoría: {product['category']}")
        if attrs.get("model"):
            lines.append(f"Modelo: {attrs['model']}")
        if attrs.get("weight_kg"):
            lines.append(f"Peso: {attrs['weight_kg']} kg")
        specs = attrs.get("specs") or {}
        if isinstance(specs, dict) and specs:
            preferred = (
                "Garantía",
                "Garantia",
                "Medidas",
                "Material",
                "Tamaño",
                "Tamano",
                "Potencia",
                "Capacidad",
                "Color",
            )
            ordered = [key for key in preferred if key in specs]
            ordered += [key for key in specs if key not in ordered]
            detail = " · ".join(
                f"{key}: {specs[key]}" for key in ordered[:4]
            )
            if detail:
                lines.append(detail[:260])
        description = self._card_description(
            attrs.get("description") or "", limit=220
        )
        if description and description.upper() != (product.get("name") or "").upper():
            lines.append(f"Descripción: {description}")
        if product.get("barcode"):
            lines.append(f"Código de barra: {product['barcode']}")
        # Complemento con stock validado: sube el ticket sin inventar nada.
        combo = await catalog.complements(
            session, product["sku"], product["name"], limit=1
        )
        if combo:
            extra = combo[0]
            lines.append(
                f"Para completar: {extra.name.title()} — Bs {extra.price} "
                f"(escribí *agregar {extra.sku}*)"
            )
        # Lista de acciones: "Agregar 1/2/3" queda atado a ESTE producto,
        # sin los botones numerados que no decían a cuál correspondían.
        rows: list[dict] = []
        if stock > 0:
            for quantity in (1, 2, 3):
                rows.append(
                    {
                        "id": f"add:{product['sku']}:{quantity}",
                        "title": f"Agregar {quantity}",
                        "description": "Al carrito",
                    }
                )
        rows.append(
            {
                "id": "catalog",
                "title": "Ver otra opción",
                "description": "Volver a buscar",
            }
        )
        rows.append(
            {
                "id": "human",
                "title": "Hablar con asesor",
                "description": "Te atiende una persona",
            }
        )
        messages = []
        image_info = await catalog.primary_image_info(
            session, product["sku"]
        )
        image_url = image_info["url"] if image_info else None
        is_placeholder = bool(
            image_info and image_info.get("source") == "demo"
        )
        if not image_url and settings.product_image_placeholder:
            image_url = settings.product_image_placeholder
            is_placeholder = True
        if image_url:
            messages.append(
                Outbound(
                    kind="image",
                    url=image_url,
                    text=(
                        "Imagen referencial"
                        if is_placeholder
                        else product["name"][:1024]
                    ),
                )
            )
        messages.append(
            Outbound(
                kind="list",
                text="\n".join(lines),
                button_text="¿Qué hacemos?",
                sections=[{"title": "Acciones", "rows": rows}],
            )
        )
        return AgentReply(messages)

    async def _add_product(
        self,
        session: AsyncSession,
        contact: Contact,
        sku: str,
        quantity: int,
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        result = await toolbox.tool_add_to_cart(sku=sku, quantity=quantity)
        if not result.get("ok"):
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=f"No pude agregarlo: {result.get('error', 'sin stock')}",
                        buttons=[
                            {"id": "catalog", "title": "Ver opciones"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        added_text = persona.added(
            result.get("name") or sku,
            f"{Decimal(result['cart_total']):,.2f}",
        )
        await funnel.track(
            session,
            "cart_add",
            contact=contact,
            sku=sku,
            value=Decimal(str(result.get("cart_total") or 0)),
        )
        # Nudge de escalón: si el cliente está cerca del siguiente precio por
        # cantidad, se lo mostramos con los datos reales de la oferta.
        current = int(result.get("quantity") or quantity)
        tiers: list[tuple[int, Decimal]] = []
        try:
            offer = await pricing.get_offer(session, sku, quantity=current)
            if offer is not None:
                tiers = [(tier.quantity, tier.price) for tier in offer.tiers]
        except Exception:  # noqa: BLE001 - el nudge es opcional
            logger.debug("No se pudo leer escalones de %s", sku, exc_info=True)
        if not tiers:
            tiers = await catalog.quantity_tiers(session, sku)
        upcoming = next((tier for tier in tiers if tier[0] > current), None)
        if upcoming:
            added_text += (
                f"\n\nOjo: desde {upcoming[0]} unidades te queda a "
                f"*Bs {upcoming[1]} c/u*."
            )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=added_text,
                    buttons=[
                        {"id": "cart", "title": "Mi carrito"},
                        {"id": "catalog", "title": "Seguir comprando"},
                    ],
                )
            ]
        )

    @staticmethod
    def _card_description(value: str, limit: int = 160) -> str:
        text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= limit:
            return text
        cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip()
        return (cut or text[: limit - 1]).rstrip() + "…"

    async def _price_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        raw: str,
        direction: str,
        base_hint: str | None = None,
    ) -> AgentReply | None:
        """Lista los artículos más baratos (o más caros) del rubro vigente."""
        conversacion = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contact.id)
        )
        state = (
            await conversation_state.get_state(session, conversacion.id)
            if conversacion is not None
            else None
        )
        base = (base_hint or "").strip() or (
            (getattr(state, "category", None) or "") if state else ""
        ).strip()
        if not base and conversacion is not None:
            base = (conversacion.last_query or "").strip()
        base = _clean_query(base)
        if not base and conversacion is not None:
            # Sin rubro guardado: se toma el último mensaje del cliente que
            # no haya sido otro pedido de precio ("tienes taladros?").
            previos = (
                await session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id == conversacion.id,
                        Message.direction == "in",
                    )
                    .order_by(Message.created_at.desc())
                    .limit(6)
                )
            ).all()
            for previo in previos:
                candidato = _clean_query(previo.text or "")
                if len(candidato) >= 4 and not _price_intent(candidato):
                    base = candidato
                    break
        if not base:
            return None

        resultado = await Toolbox(
            session, contact, self.wa
        ).tool_search_products(query=base, limit=12)
        productos = resultado.get("products") or []
        if not productos:
            return None

        def precio(producto: dict) -> float:
            valor = producto.get("promo_price") or producto.get("price") or 0
            try:
                return float(valor)
            except (TypeError, ValueError):
                return 0.0

        productos.sort(key=precio, reverse=direction == "desc")
        singular = bool(
            re.search(
                r"\b(cu[aá]l|cu[aá]les)\b.*\b(m[aá]s\s+barat|menor\s+precio|precio\s+m[aá]s\s+bajo|"
                r"m[aá]s\s+car|mayor\s+precio)",
                raw or "",
                re.IGNORECASE,
            )
        )
        elegidos = productos[:1] if singular else productos[:3]
        rubro = ((getattr(state, "category", None) or base) if state else base).strip()
        if direction == "asc":
            texto_lead = (
                f"El más barato de {rubro} es este:"
                if singular
                else f"Estos son los más baratos de {rubro}:"
            )
        else:
            texto_lead = (
                f"El más caro de {rubro} es este:"
                if singular
                else f"Estos son los más caros de {rubro}:"
            )
        self._trace(f"Orden por precio ({direction}): {rubro}")
        return AgentReply(
            [
                Outbound(text=texto_lead),
                *self._search_cards(elegidos),
            ]
        )

    @staticmethod
    def _search_cards(products: list[dict]) -> list[Outbound]:
        """Tarjetas visuales sin catálogo nativo: hasta 3 fotos + botones."""
        selected: list[dict] = []
        vistas: set[str] = set()
        for producto in products:
            clave = _fold_word(producto.get("name") or "")
            if clave in vistas:
                continue
            vistas.add(clave)
            selected.append(producto)
            if len(selected) == 3:
                break
        if not selected:
            return []
        messages: list[Outbound] = []
        for index, product in enumerate(selected, start=1):
            price = product.get("promo_price") or product.get("price")
            try:
                price_text = f"{Decimal(str(price)):,.2f}"
            except Exception:  # noqa: BLE001 - precio ya formateado
                price_text = str(price)
            caption = (
                f"*{index}. {product['name']}*\n"
                f"Precio: Bs {price_text}"
            )
            brand = (product.get("brand") or "").strip()
            if brand:
                caption += f"\nMarca: {brand}"
            category = (product.get("category") or "").strip()
            if category:
                caption += f"\nCategoría: {category}"
            description = Agent._card_description(
                product.get("description") or ""
            )
            if description:
                caption += f"\nDescripción: {description}"
            image_url = (product.get("image_url") or "").strip()
            if image_url.startswith(("http://", "https://")):
                messages.append(
                    Outbound(
                        kind="image",
                        url=image_url,
                        text=caption[:1024],
                    )
                )
            else:
                messages.append(Outbound(text=caption[:4096]))
        # En vez de botones "Agregar 1/2/3" (que no dicen a qué producto
        # corresponden), una lista con el nombre y el precio de cada opción.
        rows = []
        for index, product in enumerate(selected, start=1):
            price = product.get("promo_price") or product.get("price")
            try:
                price_text = f"{Decimal(str(price)):,.2f}"
            except Exception:  # noqa: BLE001
                price_text = str(price)
            detail = f"Bs {price_text}"
            brand = (product.get("brand") or "").strip()
            if brand:
                detail += f" · {brand}"
            rows.append(
                {
                    "id": f"product:{product['sku']}",
                    "title": Agent._truncate(
                        f"{index}. {product['name']}", 24
                    ),
                    "description": detail[:72],
                }
            )
        total = len(selected)
        encabezado = (
            "Te muestro la opción. Decime si te sirve y te paso el detalle:"
            if total == 1
            else f"Son {total} opciones. Decime cuál te interesa y te muestro el detalle:"
        )
        messages.append(
            Outbound(
                kind="list",
                text=encabezado,
                button_text="Ver opciones",
                sections=[{"title": "Opciones", "rows": rows}],
            )
        )
        return messages

    @staticmethod
    def _con_seguimiento(messages: list[Outbound]) -> list[Outbound]:
        """Agrega el cierre solo si hace falta.

        No se agrega si el bot ya cerró con lista o botones, ni si la última
        frase es una pregunta: el cliente todavía no respondió.
        """
        if messages:
            ultimo = messages[-1]
            if ultimo.kind in {"list", "buttons"}:
                return messages
            if (ultimo.text or "").strip().endswith("?"):
                return messages
        return [
            *messages,
            Outbound(
                kind="buttons",
                text="¿Seguimos?",
                buttons=Agent._search_buttons(),
            ),
        ]

    @staticmethod
    def _search_list(products: list[dict]) -> Outbound:
        rows = []
        for product in products[:9]:
            price = product.get("promo_price") or product.get("price")
            try:
                price_text = f"{Decimal(str(price)):,.2f}"
            except Exception:  # noqa: BLE001 - precio ya formateado
                price_text = str(price)
            brand = (product.get("brand") or "").strip()
            detail = f"Bs {price_text}"
            if brand:
                detail += f" · {brand}"
            rows.append(
                {
                    "id": f"product:{product['sku']}",
                    "title": Agent._truncate(product["name"], 24),
                    "description": detail[:72],
                }
            )
        return Outbound(
            kind="list",
            text="Elegí una opción para ver precio y foto:",
            button_text="Ver opciones",
            sections=[{"title": "Opciones", "rows": rows}] if rows else [],
        )

    async def _clear_cart_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        await toolbox.tool_clear_cart()
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=persona.cart_cleared(),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    @staticmethod
    def _cart_reply(result: dict) -> AgentReply:
        """Carrito con ajuste rápido del último artículo agregado."""
        items = result.get("items") or []
        if not items:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=persona.cart_empty(),
                        buttons=[
                            {"id": "catalog", "title": "Ver catálogo"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        lines = ["🛒 *Tu carrito*"]
        for item in items:
            lines.append(
                f"- {item['quantity']} × {item['name']} = "
                f"Bs {Decimal(item['line_total']):,.2f}"
            )
        lines.append(f"\n*Total: Bs {Decimal(result['total']):,.2f}*")

        last = items[-1]
        quantity = int(last["quantity"])
        lines.append(
            f"\nAjusto *{last['name']}* (x{quantity}). "
            "Para otro artículo, tocá *Ver carrito* desde su ficha."
        )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text="\n".join(lines)[:1024],
                    buttons=[
                        {"id": "checkout", "title": "Confirmar pedido"},
                        {
                            "id": f"qty:{last['sku']}:{quantity + 1}",
                            "title": "Sumar 1",
                        },
                        {
                            "id": f"qty:{last['sku']}:{max(quantity - 1, 0)}",
                            "title": "Restar 1",
                        },
                    ],
                )
            ]
        )

    async def _checkout_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        cart = await toolbox.tool_view_cart()
        if not cart["items"]:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=persona.cart_empty(),
                        buttons=[
                            {"id": "catalog", "title": "Ver catálogo"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        try:
            result = await toolbox.tool_checkout()
        except Exception as exc:  # noqa: BLE001 - no cobrar ni romper el chat
            logger.exception("Checkout falló de forma inesperada")
            await session.rollback()
            result = {"ok": False, "error": str(exc)[:200]}
        if not result.get("ok"):
            error = str(result.get("error") or "error de stock o precio")
            if any(
                token in error.lower()
                for token in ("getaddrinfo", "connect", "timeout", "httpx")
            ):
                error = "no pude comunicarme con SAP en este momento"
            elif error.startswith("PaaS "):
                # Quitamos el prefijo técnico y mostramos el motivo de SAP.
                _, _, detail = error.partition(": ")
                error = detail or error
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=persona.checkout_failed(error),
                        buttons=[
                            {"id": "cart", "title": "Ver carrito"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        return AgentReply(
            [
                Outbound(
                    text=(
                        f"Pedido {result['order_number']} generado.\n"
                        f"Total: *Bs {Decimal(result['total']):,.2f}*\n"
                        f"Paga con el QR: {result['payment_url']}"
                    )
                ),
                Outbound(
                    kind="buttons",
                    text="¿Necesitás algo más?",
                    buttons=[
                        {"id": "cart", "title": "Ver carrito"},
                        {"id": "human", "title": "Asesor"},
                    ],
                ),
            ]
        )

    async def _asked_payment(
        self, session: AsyncSession, contact: Contact
    ) -> bool:
        """¿El último mensaje del bot ofreció generar el link/QR de pago?"""
        conversation = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contact.id)
        )
        if conversation is None:
            return False
        last = await session.scalar(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.direction == "out",
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        if last is None or not last.text:
            return False
        text = _fold_word(last.text)
        return ("link" in text and ("pago" in text or "qr" in text)) or (
            "cerr" in text and "pedido" in text
        )

    async def _status_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        result = await toolbox.tool_order_status()
        if not result.get("ok"):
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "Todavía no tenés pedidos registrados. "
                            "¿Arrancamos con algo?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver catálogo"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        lines = [
            f"Pedido *{result['order_number']}* — "
            f"Total {result.get('currency', 'BOB')} "
            f"{Decimal(result['total']):,.2f}",
            f"Estado: *{result['status_label']}*",
        ]
        if result.get("invoice_doc_num"):
            lines.append(f"Factura SAP: {result['invoice_doc_num']}")
        elif result.get("status") == "paid":
            lines.append("La factura se está generando en SAP.")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text="\n".join(lines),
                    buttons=[
                        {"id": "cart", "title": "Ver carrito"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _resolve_pending(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        guard,
    ) -> AgentReply | None:
        slot = (guard.pending_slot or "").lower()
        if not slot:
            return None
        raw = (text or "").strip()
        if re.search(r"\b(asesor|humano|menu|menú|hola)\b", raw, re.I):
            await conversation_guard.clear_pending(session, contact)
            return None
        # Otra pregunta (identidad, políticas, horarios) no es la respuesta a
        # la ranura pendiente: que siga el camino normal.
        if IDENTITY_RE.search(raw) or KNOWLEDGE_RE.search(raw):
            await conversation_guard.clear_pending(session, contact)
            return None
        # La base debe ser el rubro, no la frase completa del cliente: si no,
        # se encadenan oraciones y la búsqueda recibe texto sin sentido
        # ("no gusta mejor tv" + "50 pulgadas").
        base_raw = guard.pending_query or ""
        base = _clean_query(base_raw) or base_raw
        if slot == "intent":
            await conversation_guard.clear_pending(session, contact)
            route = intent_guard.route_answer(raw)
            if route == "order":
                text = await order_tracking.start(session, contact)
                return AgentReply([Outbound(text=text)])
            if route == "return":
                rule = await rules_engine.return_rule(session)
                if rule is not None:
                    text = await return_flow.start(session, contact, rule)
                    return AgentReply([Outbound(text=text)])
                return await self._human_fallback(
                    session, contact, "Consulta de devolución o garantía"
                )
            if route in {"shipping", "payment", "invoice"}:
                knowledge = await self._knowledge_reply(
                    session, contact, raw
                )
                if knowledge is not None:
                    return knowledge
                return await self._human_fallback(
                    session, contact, raw
                )
            if route in {"product", "gift"}:
                combined = f"{base} {raw}".strip()
                event_key, event = await occasion_store.resolve(
                    session, combined
                )
                if event is not None:
                    return await self._occasion_reply(
                        session, contact, combined, event
                    )
                semantic_reply = await self._semantic_reply(
                    session, contact, combined
                )
                if semantic_reply is not None:
                    return semantic_reply
                return await self._search_reply(
                    session, contact, combined
                )
            if route == "human":
                return await self._human_fallback(
                    session, contact, raw
                )
            return None
        if slot == "topic":
            await conversation_guard.clear_pending(session, contact)
            combined = f"{base} {_clean_query(raw)}".strip()
            key, event = await occasion_store.resolve(session, combined)
            if event is not None:
                return await self._occasion_reply(
                    session, contact, combined, event
                )
            # Con una medida concreta ("50 pulgadas") conviene la búsqueda
            # normal: filtra por tamaño y no ofrece otro porte.
            if not _requested_size(combined):
                semantic_reply = await self._semantic_reply(
                    session, contact, combined
                )
                if semantic_reply is not None:
                    return semantic_reply
            return await self._search_reply(
                session, contact, combined
            )
        if slot == "size":
            size = _requested_size(raw)
            if not size:
                number = re.search(r"\b(\d{1,3})\b", raw)
                size = number.group(1) if number else None
            if not size:
                return None
            if "colch" in base.lower() or "cama" in base.lower():
                query = f"{base} {size} plazas".strip()
            else:
                query = f"{base} {size} pulgadas".strip()
            await conversation_guard.clear_pending(session, contact)
            policy = await rule_policy.build(session, query)
            return await self._search_reply(
                session, contact, query, policy=policy
            )
        if slot == "budget":
            low, high = _requested_budget(raw)
            if low is None and high is None:
                number = re.search(r"\b(\d{1,5})\b", raw)
                if number:
                    high = float(number.group(1))
            if low is None and high is None:
                return None
            await conversation_guard.clear_pending(session, contact)
            return await self._search_reply(
                session, contact, base, min_price=low, max_price=high
            )
        if slot == "quantity":
            quantity = _requested_quantity(raw)
            if quantity <= 1:
                return None
            await conversation_guard.clear_pending(session, contact)
            return await self._search_reply(
                session, contact, base, quantity=quantity
            )
        if slot == "brand":
            if not re.search(r"\b[A-Za-zÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ -]{1,40}\b", raw):
                return None
            await conversation_guard.clear_pending(session, contact)
            return await self._search_reply(
                session, contact, f"{base} {raw}".strip()
            )
        await conversation_guard.clear_pending(session, contact)
        return None

    async def _resolve_reference(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
    ) -> AgentReply | None:
        raw = (text or "").strip()
        snapshot = await recommendations.latest(session, contact.id)
        if snapshot is None or not snapshot.products:
            return None
        if re.search(
            r"\b(cu[aá]l|qu[eé])\s+me\s+(recomendaste|mostraste)\b",
            raw,
            re.I,
        ):
            explanation = recommendations.explain(snapshot)
            return AgentReply([Outbound(text=explanation)])
        ordinal = re.search(
            r"\b(primer[oa]?|segund[oa]?|tercer[oa]?|cuart[oa]?)\b",
            raw,
            re.I,
        )
        if ordinal:
            index = {
                "primer": 0, "primero": 0, "primera": 0,
                "segundo": 1, "segunda": 1,
                "tercero": 2, "tercera": 2,
                "cuarto": 3, "cuarta": 3,
            }.get(_fold_word(ordinal.group(1)), 0)
            if index < len(snapshot.products):
                product = snapshot.products[index]
                if product.get("sku"):
                    return await self._product_detail(
                        session, contact, product["sku"]
                    )
        if re.search(r"\b(ese|esa|eso|el mismo|la misma)\b", raw, re.I):
            product = snapshot.products[0]
            if product.get("sku"):
                return await self._product_detail(
                    session, contact, product["sku"]
                )
        return None

    async def postprocess(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        reply: AgentReply,
    ) -> AgentReply:
        """Garantiza salida y evita repetir exactamente la misma respuesta."""
        if not reply.messages:
            reply = AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=conversation_guard.fallback_text(),
                        buttons=[
                            {"id": "catalog", "title": "Ver productos"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        answer = "\n".join(
            message.text or "" for message in reply.messages
        ).strip()
        if not answer:
            answer = conversation_guard.fallback_text()
        # La respuesta no puede introducir un tema que nadie mencionó
        # ("¿te vas de viaje?" cuando se hablaba de Halloween).
        try:
            contexto = await coherence.contexto_reciente(
                session, contact, text
            )
            inventados = (
                [] if en_ocasion else coherence.temas_inventados(answer, contexto)
            )
        except Exception:  # noqa: BLE001 - el guard no debe romper
            logger.debug("No se pudo verificar coherencia", exc_info=True)
            inventados = []
        if inventados:
            self._trace("Respuesta incoherente: se reemplaza")
            metrics.record_coherence_block()
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "Contame un poco más para mostrarte algo que te "
                            "sirva: ¿qué estás buscando y para qué lo necesitás?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver productos"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        repeated = await conversation_guard.record_answer(
            session,
            contact,
            user_text=text,
            answer=answer,
        )
        if repeated:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=conversation_guard.loop_text(),
                        buttons=[
                            {"id": "catalog", "title": "Otras opciones"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        return reply

    async def handle(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        history: list[dict] | None = None,
        memory: str | None = None,
        media: dict | None = None,
    ) -> AgentReply:
        normalized = (text or "").strip().lower()
        raw = (text or "").strip()
        simple = re.sub(
            r"[^a-záéíóúñü ]", " ", normalized
        ).strip()
        simple = re.sub(r"\s+", " ", simple)
        toolbox = Toolbox(session, contact, self.wa)

        # Refrescar el vínculo desde la DB: evitar que una mutación en memoria
        # haga creer que el cliente ya está identificado.
        await session.refresh(contact)

        # Imagen: se interpreta y se buscan productos parecidos en el catálogo.
        if media and (media.get("kind") == "image"):
            respuesta = await self._image_reply(session, contact, media)
            if respuesta is not None:
                return respuesta

        # Privacidad: sin vínculo no se consulta historial ni se deja que la IA
        # invente "no tenés compras". Primero se pide CI/NIT.
        if _is_purchase_query(raw) and not (
            contact.tax_id or contact.sap_card_code
        ):
            return AgentReply(
                [
                    Outbound(
                        text=(
                            "Para ver tus compras, ¿me pasás tu CI o NIT? "
                            "Lo uso solo para consultar tu historial. "
                            "Si sos persona, el CI; si es empresa, el NIT."
                        )
                    )
                ]
            )

        # Flujo de devolución activo: cada respuesta alimenta el flujo, no una
        # búsqueda de productos.
        active_flow = await return_flow.get_active(session, contact)
        if active_flow:
            if HANDOFF_RE.search(raw):
                active_flow.status = "cancelled"
                await session.commit()
            else:
                outcome = await return_flow.answer(
                    session, active_flow, raw
                )
                if outcome.get("needs_handoff"):
                    await toolbox.tool_human_handoff(
                        "Flujo de devolución finalizado"
                    )
                return AgentReply([Outbound(text=outcome["text"])])

        if re.search(
            r"\b(devoluci[oó]n|devolver|cambiar\s+un\s+producto)\b",
            raw,
            re.IGNORECASE,
        ):
            rule = await rules_engine.return_rule(session)
            if rule is not None:
                text = await return_flow.start(session, contact, rule)
                return AgentReply([Outbound(text=text)])

        # Seguimiento VTEX: se pide el ID del correo y se consulta OMS.
        active_tracking = await order_tracking.get_active(session, contact)
        if active_tracking:
            if HANDOFF_RE.search(raw):
                active_tracking.status = "cancelled"
                await session.commit()
            elif re.search(
                r"\b(quiero\s+pagar|pagar\s+con|qr|tarjeta|transferencia|"
                r"cuotas?|devoluci[oó]n|garant[ií]a|reclamo|env[ií]o|"
                r"retiro|sucursal|asesor|busco|precio|comprar)\b",
                raw,
                re.IGNORECASE,
            ):
                # El cliente cambió de tema: no tratar su mensaje como ID.
                active_tracking.status = "cancelled"
                await session.commit()
            else:
                outcome = await order_tracking.lookup(
                    session, active_tracking, raw
                )
                if outcome.get("needs_handoff"):
                    await toolbox.tool_human_handoff(
                        "Seguimiento de pedido sin resultado"
                    )
                return AgentReply([Outbound(text=outcome["text"])])

        # Si el cliente ya dio su CI o NIT, se guarda y se usa en el acto:
        # no tiene sentido volver a pedirlo en el mensaje siguiente.
        documento = _document_number(raw)
        if documento and not (contact.tax_id or contact.sap_card_code):
            contact.tax_id = documento
            await session.commit()
            historial = await purchases.get_history(
                session, contact.id, limit=5
            )
            compras = historial.get("purchases") or []
            if compras:
                ultima = compras[0]
                cantidad = len(compras)
                texto = (
                    f"Listo, guardé tu documento. Tenés {cantidad} compra"
                    f"{'s' if cantidad != 1 else ''} registrada"
                    f"{'s' if cantidad != 1 else ''}. La última fue del "
                    f"{str(ultima.get('date', ''))[:10]}. "
                    "¿Querés el detalle de alguna?"
                )
            else:
                texto = (
                    "Listo, guardé tu documento. No me aparece ninguna compra "
                    "con ese dato; puede tardar en sincronizar. ¿Querés que lo "
                    "revise un asesor?"
                )
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=texto,
                        buttons=[
                            {"id": "order", "title": "Ver un pedido"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        if TRACKING_RE.search(raw):
            text = await order_tracking.start(session, contact)
            return AgentReply([Outbound(text=text)])

        # "¿Por qué me recomendaste ese?": se responde antes de cualquier
        # ranura pendiente, con datos reales del último producto visto.
        if WHY_RE.search(raw):
            why_reply = await self._why_reply(session, contact)
            if why_reply is not None:
                return why_reply

        # ¿Charla nueva en el mismo chat? Se conserva el historial (para
        # personalizar) pero se limpian rubro, marca, medida y pregunta
        # pendiente de la charla anterior.
        conversation = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contact.id)
        )
        session_info = await session_flow.start_new_if_needed(
            session, conversation, contact
        )
        if session_info.get("new"):
            gap = session_info.get("gap_minutes") or 0
            self._trace(f"Charla nueva (pausa de {gap} min)")

        # Preguntas sobre dueños o personal: el bot no tiene ese dato y no
        # debe confundirlas con "quién sos".
        if _about_company_person(raw):
            self._trace("Pregunta sobre la empresa: sin dato")
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "No tengo información sobre los dueños ni el "
                            "personal de ROHO, así que no quiero inventarla. "
                            "¿Te ayudo con productos, precios o stock?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver productos"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        # "¿Quién eres?": se responde con la identidad, nunca con productos ni
        # como si fuera la respuesta a una pregunta pendiente.
        if IDENTITY_RE.search(raw):
            self._trace("Identidad: quién soy")
            return self._identity_reply()

        # Despedida: se cierra la charla y se limpia el contexto de trabajo.
        if FAREWELL_RE.search(raw):
            self._trace("Cierre por despedida")
            return await self._farewell_reply(session, contact)

        guard = await conversation_guard.get_for_contact(session, contact)
        if guard is not None:
            reference_reply = await self._resolve_reference(
                session, contact, raw
            )
            if reference_reply is not None:
                return reference_reply
            pending_reply = await self._resolve_pending(
                session, contact, raw, guard
            )
            if pending_reply is not None:
                return pending_reply

        # Las políticas publicadas (envíos, garantías) se responden primero:
        # es mejor dar el dato que preguntar de vuelta.
        if KNOWLEDGE_RE.search(raw):
            knowledge_reply = await self._knowledge_reply(session, contact, raw)
            if knowledge_reply is not None:
                return knowledge_reply

        # "¿Por qué me recomendaste ese?": se explica con datos reales del
        # último producto visto, sin repetir la ficha.
        if WHY_RE.search(raw):
            why_reply = await self._why_reply(session, contact)
            if why_reply is not None:
                return why_reply

        ambiguous_question = intent_guard.detect(raw)
        if ambiguous_question:
            return await self._clarify_reply(
                session,
                contact,
                question=ambiguous_question,
                query=raw,
                slot="intent",
            )

        # Memoria: lo que el cliente ya dijo (medida, presupuesto) no se
        # vuelve a preguntar.
        try:
            await preferences.remember(session, contact, raw)
        except Exception:  # noqa: BLE001 - la memoria no frena la charla
            logger.exception("No se pudieron guardar las preferencias")

        # Clasificación de intención: primero reglas, y si hay duda, el modelo
        # con lista cerrada de ocasiones. Una frase personal nunca termina en
        # una lista de productos "cercanos".
        decision = await intent_service.classify(raw)
        # Temas delicados (duelo, salud, tristeza): primero la persona.
        if decision.get("sensitive"):
            self._trace("Empatía: tema delicado")
            return self._empathy_reply(decision)
        # Política: salud, legal, financiero, datos o seguridad se derivan.
        policy_topic = policy_guard.detect(raw)
        if policy_topic:
            self._trace(f"Derivación por política: {policy_topic}")
            return self._policy_reply(policy_topic)
        # Enojo o espera: disculpa y derivación inmediata, sin vender.
        if decision.get("frustrated"):
            self._trace("Enojo: disculpa y derivación")
            return await self._frustration_reply(session, contact)
        # "¿Tienen juguetes?": si el catálogo no lo tiene, se dice de entrada
        # (el modelo inventaba disponibilidad).
        termino = _availability_term(raw)
        if termino:
            caja = Toolbox(session, contact, self.wa)
            sonda = await caja.tool_search_products(
                query=termino, limit=3, ignore_state=True
            )
            if not sonda.get("products"):
                self._trace(f"Sin stock de rubro: {termino}")
                return AgentReply(
                    [
                        Outbound(
                            kind="buttons",
                            text=(
                                f"Por ahora no tenemos *{termino}* en el "
                                "catálogo. Trabajamos con artículos para el "
                                "hogar: línea blanca, colchones, muebles, "
                                "iluminación, baño, ferretería y herramientas.\n\n"
                                "¿Te muestro alguna de esas líneas o preferís "
                                "hablar con un asesor?"
                            ),
                            buttons=[
                                {"id": "catalog", "title": "Ver categorías"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        )
                    ]
                )

        # "Quiero los más baratos": se listan artículos con precio, no marcas.
        direccion = _price_intent(raw)
        entendido = None
        if (
            direccion is None
            and settings.deepseek_api_key
            and settings.understanding_enabled
            and not _COMPREHENSION_SKIP_RE.search(raw)
        ):
            # Solo se consulta al modelo cuando la regla no lo detectó: los
            # caminos rápidos (agregar, sí/no, pedido) no pagan esa latencia.
            try:
                entendido = await understanding.parse(self._llm(), raw)
            except Exception:  # noqa: BLE001 - interpretar no debe romper
                entendido = None
            direccion = (entendido or {}).get("orden_precio")
            if direccion:
                self._trace("Comprensión IA: pedido de precio")
        if direccion is not None:
            por_precio = await self._price_reply(
                session,
                contact,
                raw,
                direccion,
                base_hint=(entendido or {}).get("producto"),
            )
            if por_precio is not None:
                return por_precio

        if decision["intent"] == "personal":
            # La ocasión se busca en el panel (base), no sólo en el archivo
            # inicial: lo que el equipo publica tiene que llegar al bot.
            _key, event = await occasion_store.resolve(session, raw)
            if event is None and decision.get("occasion"):
                # La ocasión que propone el modelo solo se usa si el cliente
                # la nombró: si no, inventaba contextos ("viaje", "películas").
                candidato = occasions.EVENTS.get(decision["occasion"] or "")
                pistas = [
                    *((candidato or {}).get("aliases") or []),
                    *((candidato or {}).get("direct") or []),
                    (candidato or {}).get("label") or "",
                ]
                if any(
                    pista and _fold_word(pista) in _fold_word(raw)
                    for pista in pistas
                ):
                    event = candidato
            if decision["ambiguous"] and not _pide_producto(raw):
                return self._ambiguity_reply(event)
            if event is not None:
                self._trace(f"Personal con ocasión: {event.get('label')}")
                if decision.get("buy") or PRODUCT_REQUEST_RE.search(raw):
                    return await self._occasion_reply(
                        session, contact, raw, event
                    )
                return self._occasion_pivot(event)
            return self._personal_pivot()

        event_key, event = await occasion_store.resolve(session, raw)
        if event is not None:
            self._trace(f"Ocasión: {event.get('label')}")
            if (
                decision["ambiguous"]
                and not decision["buy"]
                and not _pide_producto(raw)
            ):
                return self._ambiguity_reply(event)
            return await self._occasion_reply(
                session, contact, raw, event
            )

        # "Algo para distraer a las visitas": es una idea, no un producto.
        # Buscar la frase entera devolvía cualquier cosa (una vela de
        # citronela); se traduce a categorías y se explican las opciones.
        idea = ideas.detect(raw)
        if idea is not None:
            self._trace(f"Idea: {idea['label']}")
            return await self._idea_reply(session, contact, idea)

        if SEMANTIC_QUERY_RE.search(raw):
            semantic_reply = await self._semantic_reply(
                session, contact, raw
            )
            if semantic_reply is not None:
                return semantic_reply
            return await self._clarify_reply(
                session,
                contact,
                question=(
                    "Para darte una buena recomendación, ¿qué tipo de cosa "
                    "buscás: algo para el hogar, para regalar, para "
                    "entretenerte o para una ocasión especial?"
                ),
                query=raw,
            )

        if RECOMMENDATION_EXPLAIN_RE.search(raw):
            result = await toolbox.tool_explain_recommendation()
            if result.get("ok"):
                return AgentReply([Outbound(text=result["explanation"])])

        policy = await rule_policy.build(session, raw)
        rule_policy.log_applied(
            policy, contact_id=contact.id, query=raw
        )
        if policy.has_product_rules and SEARCH_RE.search(raw):
            return await self._search_reply(
                session, contact, raw, policy=policy
            )

        if simple in {
            "hola",
            "buenas",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "menu",
            "inicio",
            "/start",
            "hola que tal",
            "hola como estas",
            "hola todo bien",
        }:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=persona.welcome(contact.name),
                        buttons=[
                            {"id": "search", "title": "Buscar producto"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        if normalized == "cart":
            return self._cart_reply(await toolbox.tool_view_cart())

        if normalized.startswith("qty:"):
            parts = raw.split(":")
            if len(parts) >= 3 and parts[1]:
                try:
                    quantity = int(parts[2])
                except ValueError:
                    quantity = 1
                if quantity <= 0:
                    await toolbox.tool_remove_from_cart(parts[1])
                else:
                    await toolbox.tool_update_cart_quantity(parts[1], quantity)
                return self._cart_reply(await toolbox.tool_view_cart())

        if normalized.startswith("remove:"):
            sku = raw.split(":", 1)[1].strip()
            if sku:
                await toolbox.tool_remove_from_cart(sku)
            return self._cart_reply(await toolbox.tool_view_cart())

        if normalized == "human" or HANDOFF_RE.search(raw):
            await toolbox.tool_human_handoff("El cliente pidió un asesor")
            return AgentReply([Outbound(text=persona.handoff())])

        if COMPLAINT_RE.search(raw):
            await toolbox.tool_human_handoff("Reclamo o cambio de producto")
            return AgentReply(
                [
                    Outbound(
                        text=(
                            "Lamento lo ocurrido. Ya avisé a alguien del equipo "
                            "para revisar el caso. ¿Me contás qué producto es y "
                            "qué pasó?"
                        )
                    )
                ]
            )

        if CLEAR_CART_RE.search(raw):
            return await self._clear_cart_reply(session, contact)

        if STATUS_RE.search(raw):
            return await self._status_reply(session, contact)

        if KNOWLEDGE_RE.search(raw):
            knowledge_reply = await self._knowledge_reply(session, contact, raw)
            if knowledge_reply is not None:
                return knowledge_reply

        # "¿Por qué me recomendaste ese?": se explica con datos, sin repetir
        # la ficha.
        if WHY_RE.search(raw):
            why_reply = await self._why_reply(session, contact)
            if why_reply is not None:
                return why_reply

        if PAYMENT_METHOD_RE.search(raw):
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "No tengo confirmados los medios de pago en este "
                            "momento. ¿Querés que lo revise un asesor?"
                        ),
                        buttons=[
                            {"id": "human", "title": "Asesor"},
                            {"id": "catalog", "title": "Ver productos"},
                        ],
                    )
                ]
            )

        if (
            CHECKOUT_RE.search(raw)
            and not PAYMENT_METHOD_RE.search(raw)
            and normalized not in {
                "formas de pago",
                "medios de pago",
            }
        ):
            return await self._checkout_reply(session, contact)

        if _is_purchase_query(raw):
            if not (contact.tax_id or contact.sap_card_code):
                return AgentReply(
                    [
                        Outbound(
                            text=(
                                "Para ver tus compras, ¿me pasás tu CI o NIT? "
                                "Lo uso solo para consultar tu historial. "
                                "Si sos persona, el CI; si es empresa, el NIT."
                            )
                        )
                    ]
                )
            if settings.deepseek_api_key:
                self._trace("Modelo de IA")
                return await self._llm_handle(
                    session, contact, raw, history or [], memory
                )
            return await self._purchase_history_reply(session, contact)

        if SEARCH_RE.search(raw):
            # Sin un término de producto ("quién eres", "gracias"), no se
            # busca a ciegas: se responde conversando.
            if not catalog._relevance_terms(raw):
                if settings.deepseek_api_key:
                    self._trace("Modelo de IA (charla)")
                    return await self._llm_handle(
                        session, contact, raw, history or [], memory
                    )
                self._trace("Reglas (charla)")
                return await self._demo(session, contact, raw)
            if settings.deepseek_api_key:
                self._trace("Modelo de IA")
                return await self._llm_handle(
                    session, contact, raw, history or [], memory
                )
            return await self._search_reply(session, contact, raw)

        if normalized.startswith("cat:"):
            category = raw.split(":", 1)[1].strip()
            return await self._product_list(session, contact, category)

        if normalized.startswith("product:"):
            sku = raw.split(":", 1)[1].strip()
            return await self._product_detail(session, contact, sku)

        # Botón de la pregunta de medida/marca: se combina con la búsqueda previa.
        if normalized.startswith("refine:"):
            option = raw.split(":", 1)[1].strip()
            conversation = await session.scalar(
                select(Conversation).where(Conversation.contact_id == contact.id)
            )
            base = (conversation.last_query if conversation else None) or ""
            if not base:
                # Botón viejo o conversación sin contexto: no buscamos a ciegas.
                return AgentReply(
                    [
                        Outbound(
                            kind="buttons",
                            text=(
                                f"¿Sobre qué producto querés que busque "
                                f"*{option}*?"
                            ),
                            buttons=[
                                {"id": "search", "title": "Buscar producto"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        )
                    ]
                )
            combined = f"{base} {option}".strip()
            local = await catalog.search_items(session, combined, limit=5)
            needle = option.lower()
            matches = [
                row
                for row in local
                if needle in (row.name or "").lower()
                or needle in (row.brand or "").lower()
            ]
            if matches:
                return await self._search_reply(
                    session, contact, combined, limit=3
                )
            # Sin coincidencias locales no vale la pena ir a SAP: se responde
            # al instante y se ofrece otra opción.
            topic = catalog.primary_term(base) or base or "eso"
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            f"No tengo *{option}* en {topic}. "
                            "¿Probamos otra medida o marca?"
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver opciones"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        # Código de barra (EAN/UPC): se resuelve directo, sin LLM.
        barcode = catalog.barcode_from_text(raw)
        if barcode:
            hit = await catalog.get_by_barcode(session, barcode)
            if hit is not None:
                return await self._product_detail(session, contact, hit.sku)

        if normalized.startswith("find:"):
            term = raw.split(":", 1)[1].strip()
            if term:
                return await self._search_reply(session, contact, term)

        if normalized.startswith("add:"):
            parts = raw.split(":")
            if len(parts) >= 2 and parts[1]:
                try:
                    quantity = int(parts[2]) if len(parts) > 2 else 1
                except ValueError:
                    quantity = 1
                return await self._add_product(
                    session, contact, parts[1], max(quantity, 1)
                )

        # "agregar SKU 2" en texto libre: mismo atajo que el botón, sin LLM.
        for prefix in ("agregar ", "añadir ", "anadir "):
            if normalized.startswith(prefix):
                parts = raw[len(prefix) :].split()
                if not parts:
                    break
                sku = parts[0].upper()
                if await catalog.get_item(session, sku) is None:
                    break
                quantity = 1
                if len(parts) > 1 and parts[1].isdigit():
                    quantity = int(parts[1])
                return await self._add_product(
                    session, contact, sku, max(quantity, 1)
                )

        # Un "sí" tras ofrecer el link de pago cierra el pedido, sin LLM.
        if AFFIRMATIVE_RE.match(simple) and await self._asked_payment(
            session, contact
        ):
            return await self._checkout_reply(session, contact)

        if normalized == "search":
            return AgentReply(
                [Outbound(text=persona.ask_need())]
            )

        if normalized in {"more", "filter"} or normalized.startswith("price:"):
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.contact_id == contact.id
                )
            )
            last_query = (
                conversation.last_query if conversation is not None else None
            )
            if not last_query:
                return AgentReply(
                    [Outbound(text=persona.ask_need())]
                )
            if normalized == "more":
                return await self._search_reply(
                    session, contact, last_query, limit=9
                )
            if normalized == "filter":
                return AgentReply(
                    [
                        Outbound(
                            kind="buttons",
                            text="¿Qué rango de precio te acomoda?",
                            buttons=[
                                {"id": "price:0:500", "title": "Hasta Bs 500"},
                                {"id": "price:500:1500", "title": "Bs 500 a 1500"},
                                {"id": "price:1500:999999", "title": "Más de Bs 1500"},
                            ],
                        )
                    ]
                )
            parts = raw.split(":")
            try:
                min_price = float(parts[1])
                max_price = float(parts[2])
            except (IndexError, ValueError):
                return AgentReply([Outbound(text=persona.ask_need())])
            return await self._search_reply(
                session,
                contact,
                last_query,
                min_price=min_price,
                max_price=max_price,
            )

        if normalized == "explore":
            return await self._category_list(session, contact)

        if normalized == "catalog" and not native_commerce.is_ready():
            return await self._category_list(session, contact)

        if (
            re.search(r"\bcat[aá]logo\b", raw, re.IGNORECASE)
            and not re.search(
                r"\b(oferta|promoci[oó]n|descuento|precio)\b",
                raw,
                re.IGNORECASE,
            )
        ):
            return await self._category_list(session, contact)

        if native_commerce.is_ready() and re.search(
            r"\b(cat[aá]logo|productos)\b", text or "", re.IGNORECASE
        ):
            return AgentReply(
                [
                    Outbound(
                        kind="catalog",
                        text=(
                            "Este es nuestro catálogo ROHO. "
                            "Elegí lo que te guste y te ayudo con el pedido."
                        ),
                        catalog_id=settings.wa_catalog_id,
                    )
                ]
            )
        # Respuesta corta a una pregunta anterior ("2 plazas", "marca Flex"):
        # se combina con la última búsqueda si por sí sola no encuentra nada.
        if (
            1 <= len(simple.split()) <= 4
            and simple not in _CONTROL_WORDS
            and not any(word in _STOPWORDS for word in simple.split())
        ):
            conversation = await session.scalar(
                select(Conversation).where(Conversation.contact_id == contact.id)
            )
            last = (conversation.last_query or "").strip() if conversation else ""
            if last and _fold_word(last) not in simple:
                display = _clean_query(raw) or raw
                probe = await Toolbox(session, contact, self.wa).tool_search_products(
                    query=f"{last} {display}".strip(), limit=3
                )
                if probe.get("products"):
                    return AgentReply(
                        self._con_seguimiento(
                            [
                                Outbound(
                                    text=(
                                        f"Con *{display}* tengo estas opciones:"
                                    )
                                ),
                                *self._search_cards(probe["products"]),
                            ]
                        )
                    )

        if not settings.deepseek_api_key:
            self._trace("Reglas del catálogo (sin modelo)")
            return await self._demo(session, contact, text)
        try:
            self._trace("Modelo de IA")
            return await self._llm_handle(
                session, contact, text, history or [], memory
            )
        except Exception:  # noqa: BLE001 - fallback para no dejar al cliente sin respuesta
            logger.exception("Fallo el agente LLM; se usa el modo demo")
            self._trace("Reglas del catálogo (sin modelo)")
            return await self._demo(session, contact, text)

    async def _promotion_preflight(
        self, text: str, toolbox: Toolbox
    ) -> str | None:
        if not PROMO_RE.search(text or ""):
            return None
        try:
            result = await toolbox.tool_list_promotions(limit=5)
        except Exception:  # noqa: BLE001 - el LLM puede reintentar
            logger.exception("No se pudo precargar promociones")
            return None
        promotions = result.get("promotions") or []
        if not promotions:
            return (
                "Datos reales de promociones: no hay promociones vigentes con "
                "stock en este momento. No inventes ninguna."
            )
        lines = [
            "Datos reales de promociones vigentes (usar estos datos; no inventar):"
        ]
        for promo in promotions:
            valid = promo.get("valid_to") or "sin fecha"
            lines.append(
                f"- {promo['name']} (SKU {promo['sku']}): "
                f"Bs {promo['final_price']} antes Bs {promo['base_price']} "
                f"(-{promo['discount_percent']}%), hasta {valid}."
            )
        return "\n".join(lines)

    async def _recommendation_preflight(
        self, text: str, toolbox: Toolbox
    ) -> str | None:
        """Precarga los más vendidos para que el modelo no gaste un turno.

        Cada turno extra del LLM cuesta ~2 s; con el contexto ya presente suele
        responder en la primera pasada.
        """
        if not RECO_RE.search(text or ""):
            return None
        if EXPLAIN_RE.search(text or ""):
            return None
        try:
            result = await toolbox.tool_get_best_sellers(limit=5)
        except Exception:  # noqa: BLE001 - es sólo contexto adicional
            logger.exception("No se pudieron precargar los más vendidos")
            return None
        products = result.get("products") or []
        if not products:
            return None
        lines = [
            "Más vendidos (contexto; si alcanza, respondé sin llamar otra "
            "herramienta de búsqueda):"
        ]
        for product in products[:5]:
            lines.append(
                f"- {product['name']} — Bs {product['price']}"
            )
        return "\n".join(lines)

    async def _farewell_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply:
        """Cierre amable: apaga la charla sin borrar el historial."""
        try:
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.contact_id == contact.id
                )
            )
            if conversation is not None:
                estado = await conversation_state.get_state(
                    session, conversation.id
                )
                estado.category = None
                estado.brand = None
                estado.size = None
                estado.min_price = None
                estado.max_price = None
                estado.intent = None
                estado.last_sku = None
                conversation.last_query = None
                await session.commit()
            await conversation_guard.clear_pending(session, contact)
        except Exception:  # noqa: BLE001 - la despedida no se pierde
            logger.exception("No se pudo cerrar la charla")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "¡Gracias a vos! 👋 Quedo por acá cuando quieras "
                        "retomar. Si necesitás algo más, escribime."
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Hablar con alguien"},
                    ],
                )
            ]
        )

    @staticmethod
    def _identity_reply() -> AgentReply:
        """Quién es el bot y qué puede hacer, sin vender ni buscar."""
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Soy *Rohi*, la asesora virtual de ROHO Homecenter. "
                        "Te ayudo a encontrar productos, precios y promociones, "
                        "armo tu carrito y coordino la entrega.\n\n"
                        "Soy un asistente automático; si necesitás a una "
                        "persona del equipo, la llamo."
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Hablar con alguien"},
                    ],
                )
            ]
        )

    async def _why_reply(
        self, session: AsyncSession, contact: Contact
    ) -> AgentReply | None:
        """Explica por qué se recomendó el último producto visto, con datos.

        Evita el rebote de volver a mostrar la misma ficha cuando el cliente
        pregunta "¿por qué ese?".
        """
        sku = await session.scalar(
            select(FunnelEvent.sku)
            .where(
                FunnelEvent.contact_id == contact.id,
                FunnelEvent.step == "search",
                FunnelEvent.sku.is_not(None),
            )
            .order_by(FunnelEvent.created_at.desc())
            .limit(1)
        )
        if not sku:
            sku = await session.scalar(
                select(FunnelEvent.sku)
                .where(
                    FunnelEvent.contact_id == contact.id,
                    FunnelEvent.step == "product_view",
                    FunnelEvent.sku.is_not(None),
                )
                .order_by(FunnelEvent.created_at.desc())
                .limit(1)
            )
        if not sku:
            # La herramienta de búsqueda guarda el último SKU en el estado
            # de la conversación.
            conversation = await session.scalar(
                select(Conversation).where(
                    Conversation.contact_id == contact.id
                )
            )
            if conversation is not None:
                state = await conversation_state.get_state(
                    session, conversation.id
                )
                sku = state.last_sku
        if not sku:
            # Último recurso: repetir la última búsqueda y explicar el primero.
            last_query = await session.scalar(
                select(FunnelEvent.query)
                .where(
                    FunnelEvent.contact_id == contact.id,
                    FunnelEvent.step == "search",
                    FunnelEvent.query.is_not(None),
                )
                .order_by(FunnelEvent.created_at.desc())
                .limit(1)
            )
            if not last_query:
                return None
            found = await catalog.search_items(
                session, last_query, limit=1
            )
            if not found:
                return None
            sku = found[0].sku
        item = await catalog.get_item(session, sku)
        if item is None:
            return None

        points = [f"precio Bs {Decimal(str(item.price)):,.2f}"]
        promo = await session.scalar(
            select(ProductPromotion)
            .where(ProductPromotion.sku == item.sku)
            .order_by(ProductPromotion.price)
            .limit(1)
        )
        if promo is not None:
            points.append(
                f"con descuento a Bs {Decimal(str(promo.price)):,.2f}"
            )
        if item.brand:
            points.append(f"marca {item.brand}")
        if item.category:
            points.append(f"categoría {item.category}")
        if (item.stock or 0) > 0:
            points.append("disponible ahora")

        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        f"Te mostré *{item.name}* por {', '.join(points)}.\n\n"
                        "Si querés, lo comparo con otra opción de la misma "
                        "medida o busco algo más económico."
                    ),
                    buttons=[
                        {"id": "more", "title": "Comparar opciones"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _knowledge_reply(
        self, session: AsyncSession, contact: Contact, text: str
    ) -> AgentReply | None:
        """Responde el FAQ directo desde la base, sin gastar un turno del LLM.

        Devuelve ``None`` si el artículo no es claramente pertinente, para que
        el modelo converse con contexto.
        """
        if not KNOWLEDGE_RE.search(text or ""):
            return None
        toolbox = Toolbox(session, contact, self.wa)
        try:
            result = await toolbox.tool_search_knowledge(text)
        except Exception:  # noqa: BLE001 - el LLM puede responder igual
            logger.exception("No se pudo consultar la base de conocimiento")
            return None

        articles = result.get("articles") or []
        if not articles:
            return None
        self._trace("Política publicada")

        terms = [
            _fold_word(word)
            for word in re.split(r"[^\wáéíóúñü]+", text or "")
            if len(word) > 3
        ]
        top = articles[0]
        title = _fold_word(top.get("title") or "")
        if not any(term and term in title for term in terms):
            return None

        body = normalize_whatsapp_text((top.get("content") or "").strip())
        # Sin encabezados markdown ni líneas vacías de más: se lee como chat.
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = re.sub(r"^\s*[-*]\s+", "• ", body, flags=re.MULTILINE)
        if not body:
            return None
        if len(body) > 700:
            body = body[:700].rsplit(" ", 1)[0] + "…"

        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=f"*{top.get('title', '')}*\n\n{body}",
                    buttons=[
                        {"id": "catalog", "title": "Ver catálogo"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _llm_handle(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        history: list[dict],
        memory: str | None = None,
    ) -> AgentReply:
        toolbox = Toolbox(session, contact, self.wa)
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        try:
            current_context = await context.context_line()
        except Exception:  # noqa: BLE001 - el contexto es opcional
            current_context = ""
        if current_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Contexto actual (usalo solo si suma; no lo recites "
                        "como robot): " + current_context
                    ),
                }
            )
        known_prefs = preferences.summary(
            await preferences.known(session, contact)
        )
        if known_prefs:
            messages.append({"role": "system", "content": known_prefs})
        if memory:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Memoria del cliente (úsala para no repetir preguntas "
                        "y personalizar; no la recites literalmente):\n"
                        + memory
                    ),
                }
            )
        conversation = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contact.id)
        )
        if conversation is None:
            conversation = Conversation(contact_id=contact.id)
            session.add(conversation)
            await session.flush()
        state = await conversation_state.get_state(session, conversation.id)
        state_text = conversation_state.state_text(state)
        if state_text:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Estado estructurado de la conversación: "
                        f"{state_text}. Mantené el rubro si el cliente solo "
                        "agrega marca o medida; cambialo si pide otro rubro."
                    ),
                }
            )
        policy = await rule_policy.build(
            session,
            text,
            category=state.category,
            intent=state.intent,
        )
        rule_policy.log_applied(
            policy, contact_id=contact.id, query=text
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    f"Áreas detectadas: {', '.join(policy.areas)}.\n"
                    + policy.prompt_text()
                ),
            }
        )
        promo_context = await self._promotion_preflight(text, toolbox)
        if promo_context:
            messages.append({"role": "system", "content": promo_context})
        reco_context = await self._recommendation_preflight(text, toolbox)
        if reco_context:
            messages.append({"role": "system", "content": reco_context})
        # Ventana corta: el historial largo encarece el prompt y agrega latencia
        # sin mejorar la respuesta.
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": text})

        for ronda in range(4):
            try:
                completion = await self._llm().chat.completions.create(
                    model=settings.deepseek_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.2,
                    # Modo no-thinking: menor latencia y no exige devolver
                    # reasoning_content en cada turno con tools.
                    extra_body={"thinking": {"type": "disabled"}},
                )
            except Exception:  # noqa: BLE001 - el cliente no queda sin respuesta
                logger.exception(
                    "El proveedor de IA falló; se responde con las reglas"
                )
                self._trace("Reglas del catálogo (sin modelo)")
                return await self._demo(session, contact, text)
            usage = getattr(completion, "usage", None)
            if usage is not None:
                # Los tokens cacheados llegan en un campo extra (no tipado por
                # el SDK): se leen del volcado.
                extra = getattr(usage, "model_extra", None) or {}
                cache_hit = extra.get("prompt_cache_hit_tokens") or 0
                if not cache_hit:
                    details = getattr(usage, "prompt_tokens_details", None)
                    cache_hit = getattr(details, "cached_tokens", 0) or 0
                metrics.record_tokens(
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                    settings.deepseek_model,
                    cache_hit=cache_hit,
                )
            choice = completion.choices[0].message
            if not choice.tool_calls:
                answer = _remove_stock_phrases(
                    _remove_query_echo((choice.content or "").strip(), text)
                )
                if _is_purchase_query(text) and not (
                    contact.tax_id or contact.sap_card_code
                ):
                    answer = (
                        "Para buscar tus compras, ¿me pasás tu CI o NIT? "
                        "Lo uso solo para consultar tu historial. "
                        "Si sos persona, el CI; si es empresa, el NIT."
                    )
                if toolbox.last_checkout and (
                    toolbox.last_checkout["payment_url"] not in answer
                ):
                    answer += (
                        f"\n\nPaga aquí: {toolbox.last_checkout['payment_url']}"
                    )
                if toolbox.last_checkout and settings.feedback_after_checkout:
                    answer += (
                        "\n\nSi querés, contame: ¿cómo calificás la atención "
                        "de 1 a 5? (opcional)"
                    )
                outbound = [
                    Outbound(
                        text=normalize_whatsapp_text(
                            answer or "¿Me repites la pregunta?"
                        )
                    )
                ]
                if toolbox.last_catalog:
                    catalog = toolbox.last_catalog
                    outbound.append(
                        Outbound(
                            kind=catalog["kind"],
                            text=catalog["text"],
                            catalog_id=settings.wa_catalog_id,
                            product_retailer_id=catalog.get(
                                "product_retailer_id", ""
                            ),
                            sections=catalog.get("sections", []),
                        )
                    )
                elif toolbox.last_search:
                    products = toolbox.last_search.get("products") or []
                    if products:
                        outbound.extend(self._search_cards(products))
                if toolbox.last_checkout:
                    outbound.append(
                        Outbound(
                            kind="buttons",
                            text="¿Necesitás algo más?",
                            buttons=[
                                {"id": "catalog", "title": "Ver catálogo"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        )
                    )
                elif toolbox.last_cart:
                    outbound.append(
                        Outbound(
                            kind="buttons",
                            text="¿Seguimos?",
                            buttons=[
                                {"id": "catalog", "title": "Seguir comprando"},
                                {"id": "human", "title": "Asesor"},
                            ],
                        )
                    )
                return AgentReply(self._con_seguimiento(outbound))

            # Si el modelo pidió una lectura que ya sabemos responder, se
            # contesta con el motor de reglas: evita una segunda llamada con
            # los resultados del catálogo (~2.000 tokens) y ~1 s de latencia.
            if ronda == 0 and len(choice.tool_calls) == 1:
                direct = await self._direct_reply_for_tool(
                    session, contact, choice.tool_calls[0]
                )
                if direct is not None:
                    logger.info(
                        "Respuesta directa sin segunda llamada: %s",
                        choice.tool_calls[0].function.name,
                    )
                    return direct

            messages.append(
                {
                    "role": "assistant",
                    "content": choice.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments or "{}",
                            },
                        }
                        for call in choice.tool_calls
                    ],
                }
            )
            for call in choice.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = await toolbox.dispatch(call.function.name, arguments)
                logger.info("Herramienta ejecutada: %s", call.function.name)
                if isinstance(result, dict) and result.get("error"):
                    logger.warning(
                        "Herramienta %s devolvió error: %s",
                        call.function.name,
                        result.get("error"),
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        # El modelo gastó los turnos llamando herramientas sin cerrar. Pedimos
        # un cierre sin herramientas para no dejar al cliente sin respuesta.
        answer = ""
        try:
            completion = await self._llm().chat.completions.create(
                model=settings.deepseek_model,
                messages=messages
                + [
                    {
                        "role": "system",
                        "content": (
                            "Cerrá ahora la respuesta al cliente con la "
                            "información que ya tenés. No llames herramientas."
                        ),
                    }
                ],
                temperature=0.2,
                extra_body={"thinking": {"type": "disabled"}},
            )
            answer = (completion.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001 - nunca dejar al cliente sin respuesta
            logger.exception("No se pudo cerrar la respuesta del LLM")

        if answer:
            products = (toolbox.last_search or {}).get("products") or []
            if policy.violates_brand(answer, products):
                logger.warning(
                    "Respuesta no cumple la marca prioritaria %s; "
                    "se replantea con búsqueda determinista",
                    policy.brand,
                )
                return await self._search_reply(
                    session, contact, text, policy=policy
                )
            return AgentReply([Outbound(text=answer)])

        logger.warning(
            "El LLM agotó los turnos de herramientas; se usa el modo demo"
        )
        self._trace("Reglas del catálogo (sin modelo)")
        return await self._demo(session, contact, text)

    async def _demo(
        self, session: AsyncSession, contact: Contact, text: str
    ) -> AgentReply:
        """Agente determinista para desarrollo, sin costo ni API key."""
        toolbox = Toolbox(session, contact, self.wa)
        raw = text.strip()
        normalized = raw.lower()

        if normalized in {
            "hola",
            "buenas",
            "buenos días",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "menu",
            "menú",
            "inicio",
            "/start",
        }:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "¡Hola! Soy el asistente de la tienda. Puedo buscarte "
                            "productos, armar tu carrito y generar el QR de pago.\n\n"
                            "Escribe qué buscas (ej. \"maceta\" o \"algo para la sala\") "
                            "o usa el menú."
                        ),
                        buttons=[
                            {"id": "catalog", "title": "Ver catálogo"},
                            {"id": "cart", "title": "Ver carrito"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        if normalized in {"catalog", "catálogo", "catalogo", "ver catálogo"}:
            return await self._demo_search(session, contact, "", toolbox)

        if normalized in {"cart", "carrito", "ver carrito", "mi carrito"}:
            return await self._demo_cart(session, contact, toolbox)

        if normalized in {"checkout", "confirmar", "confirmar pedido", "pagar"}:
            return await self._demo_checkout(session, contact, toolbox)

        if normalized in {"estado", "pedido", "mi pedido", "estado del pedido"}:
            result = await toolbox.tool_order_status()
            if not result.get("ok"):
                return AgentReply(
                    [Outbound(text="Todavía no tienes pedidos. ¿Te muestro el catálogo?")]
                )
            return AgentReply(
                [
                    Outbound(
                        text=(
                            f"Pedido {result['order_number']}: "
                            f"{result['status_label']} por {money(result['total'])}."
                        )
                    )
                ]
            )

        if normalized in {"human", "asesor", "humano"}:
            await toolbox.tool_human_handoff("El cliente pidió un asesor")
            return AgentReply(
                [
                    Outbound(
                        text=(
                            "Listo, te derivé con un asesor. Te responderá por este "
                            "mismo chat lo antes posible."
                        )
                    )
                ]
            )

        if normalized.startswith("[") and normalized.endswith("]"):
            return AgentReply(
                [
                    Outbound(
                        text=(
                            "Por ahora sólo puedo leer texto. Escríbeme lo que "
                            "necesitas y te ayudo."
                        )
                    )
                ]
            )

        if normalized.startswith("add:"):
            _, sku, *rest = raw.split(":")
            quantity = int(rest[0]) if rest and rest[0].isdigit() else 1
            return await self._demo_add(session, contact, sku, quantity, toolbox)

        for prefix in ("agregar ", "añadir ", "anadir "):
            if normalized.startswith(prefix):
                parts = raw[len(prefix) :].split()
                sku = parts[0]
                quantity = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                return await self._demo_add(session, contact, sku, quantity, toolbox)

        if normalized.startswith("buscar "):
            return await self._demo_search(
                session, contact, raw[len("buscar ") :], toolbox
            )

        return await self._demo_search(session, contact, _clean_query(raw), toolbox)

    async def _demo_search(
        self,
        session: AsyncSession,
        contact: Contact,
        query: str,
        toolbox: Toolbox,
    ) -> AgentReply:
        result = await toolbox.tool_search_products(query, limit=5)
        products = result.get("products", [])
        if not products:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=(
                            "No encontré productos con ese criterio. Prueba con otra "
                            "palabra o pide un asesor."
                        ),
                        buttons=[
                            {"id": "human", "title": "Asesor"},
                            {"id": "catalog", "title": "Ver catálogo"},
                        ],
                    )
                ]
            )

        lines = ["Esto es lo que tengo:"]
        for index, product in enumerate(products, start=1):
            lines.append(
                f"\n{index}. *{product['name']}* — {money(product['price'])}"
            )
        lines.append(
            "\nDecime cuál te interesa y te muestro la ficha con fotos."
        )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text="\n".join(lines)[:1024],
                    buttons=[
                        {"id": "cart", "title": "Ver carrito"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _demo_add(
        self,
        session: AsyncSession,
        contact: Contact,
        sku: str,
        quantity: int,
        toolbox: Toolbox,
    ) -> AgentReply:
        result = await toolbox.tool_add_to_cart(sku.strip().upper(), quantity)
        if not result.get("ok"):
            return AgentReply(
                [Outbound(text=f"No pude agregarlo: {result.get('error')}")]
            )
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        f"Agregado. Llevas {result['count']} unidad(es) por "
                        f"{money(result['cart_total'])}."
                        + (
                            f"\nTienda: {result['store_name']}."
                            if result.get("store_name")
                            else ""
                        )
                        + (
                            f"\nDescuento aplicado: {result['discount_percent']}%."
                            if result.get("discount_percent")
                            and float(result["discount_percent"]) > 0
                            else ""
                        )
                    ),
                    buttons=[
                        {"id": "cart", "title": "Ver carrito"},
                        {"id": "checkout", "title": "Confirmar pedido"},
                        {"id": "catalog", "title": "Seguir viendo"},
                    ],
                )
            ]
        )

    async def _demo_cart(
        self, session: AsyncSession, contact: Contact, toolbox: Toolbox
    ) -> AgentReply:
        summary = await toolbox.tool_view_cart()
        if not summary.get("items"):
            return AgentReply(
                [Outbound(text="Tu carrito está vacío. ¿Qué producto buscas?")]
            )
        lines = ["🛒 *Tu carrito*"]
        for line in summary["items"]:
            store = f" · {line['store_name']}" if line.get("store_name") else ""
            discount = (
                f" (dto. {line['discount_percent']}%)"
                if line.get("discount_percent")
                and float(line["discount_percent"]) > 0
                else ""
            )
            lines.append(
                f"- {line['quantity']} × {line['name']} = "
                f"{money(line['line_total'])}{store}{discount}"
            )
        lines.append(f"\n*Total: {money(summary['total'])}*")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text="\n".join(lines)[:1024],
                    buttons=[
                        {"id": "checkout", "title": "Confirmar pedido"},
                        {"id": "catalog", "title": "Seguir viendo"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    async def _demo_checkout(
        self, session: AsyncSession, contact: Contact, toolbox: Toolbox
    ) -> AgentReply:
        result = await toolbox.tool_checkout()
        if not result.get("ok"):
            return AgentReply(
                [Outbound(text=f"No pude generar el pedido: {result.get('error')}")]
            )
        return AgentReply(
            [
                Outbound(
                    kind="cta",
                    text=(
                        f"Pedido *{result['order_number']}* por "
                        f"{money(result['total'])}.\n"
                        "Escanea el QR o abre el link para pagar. El link vence en "
                        f"{settings.payment_ttl_minutes} minutos."
                    ),
                    cta_text="Pagar con QR",
                    url=result["payment_url"],
                )
            ]
        )
