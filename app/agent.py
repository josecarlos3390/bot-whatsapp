from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from openai import AsyncOpenAI
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import context, persona
from .config import settings
from .models import (
    CatalogItem,
    Contact,
    Conversation,
    Handoff,
    ProductPromotion,
)
from .services import (
    cart as cart_service,
    catalog,
    customer_analysis,
    customers,
    feedback,
    handoffs,
    knowledge,
    memory as memory_service,
    native_commerce,
    orders,
    pricing,
    purchases,
    sales_stats,
)
from .sap import SapError, ServiceLayerSap, get_sap
from .whatsapp import Outbound, WhatsAppClient, normalize_whatsapp_text

logger = logging.getLogger(__name__)


def money(amount: Decimal | int | float | str) -> str:
    value = Decimal(amount).quantize(Decimal("0.01"))
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"Bs {formatted}"


_STOPWORDS = {
    "quiero",
    "necesito",
    "busco",
    "buscame",
    "buscar",
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
    "puedes",
    "mostrar",
    "tienes",
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
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    return " ".join(w for w in words if w.lower() not in _STOPWORDS)


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
                "rango de precio o solo con descuento."
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
                    "min_price": {"type": "number", "minimum": 0},
                    "max_price": {"type": "number", "minimum": 0},
                    "only_discount": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                },
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
                    "min_price": {"type": "number", "minimum": 0},
                    "max_price": {"type": "number", "minimum": 0},
                    "only_discount": {"type": "boolean"},
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
            "name": "record_feedback",
            "description": (
                "Guarda feedback del cliente sobre atención, entrega, producto "
                "o un reclamo. Solo si el cliente acepta responder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "service",
                            "delivery",
                            "product",
                            "complaint",
                            "open",
                        ],
                    },
                    "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                    "comment": {"type": "string"},
                    "order_number": {"type": "string"},
                    "sku": {"type": "string"},
                    "consent": {"type": "boolean"},
                },
                "required": ["type", "consent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skip_feedback",
            "description": (
                "Marca una encuesta pendiente como omitida cuando el cliente "
                "no quiere responder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_feedback_summary",
            "description": (
                "Devuelve promedio, cantidad y últimos comentarios de feedback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                },
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
                "compra, categorías y facturas recientes con productos."
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
                "Vincula el contacto con el CardCode confirmado y sincroniza "
                "su historial de compras. Solo tras confirmar nombre."
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
Vendes por WhatsApp y tu objetivo es ayudar al cliente a encontrar lo que
necesita y cerrar la venta, sin presionar.

Personalidad:
- Cálida, resolutiva y orgullosa del hogar boliviano. Hablás como una asesora
  de tienda que conoce los productos, no como un formulario.
- Cercana pero profesional. Tutea. Usá "¡Hola!" y el nombre del cliente si lo
  tenés.
- Emojis con moderación: máximo 2 por mensaje y solo si suman calidez.
  Nunca en un reclamo, error de pago o tema serio.
- Humor sutil, nunca forzado. No digas "estimado cliente" ni "soy un robot".
- Usá el saludo de la hora (buenos días/tardes/noches) cuando corresponda.
  Si hay feriado o clima en el contexto, mencionarlo solo si aporta; no lo
  repitas en cada mensaje ni inventes datos.
- No repitas el saludo en cada mensaje ni empieces con "Encontré estas
  opciones" de forma seca.

Estilo:
- Español boliviano, cálido y conversacional. Máximo 5 líneas por respuesta.
- Haz una pregunta a la vez; no interrogues.
- Si el cliente ya dijo qué busca, primero mostrale 2-3 opciones con precio;
  después preguntá medida, estilo o presupuesto. No lo interrogues antes de
  dar valor.
- Sé concreto: pocas opciones, bien explicadas.

Método de venta:
1. Descubre la necesidad: uso, ocasión, espacio, presupuesto o estilo.
2. Busca con search_products y recomienda 1 o 2 opciones concretas.
   Si pide “colchones en descuento”, “de la marca X” o “hasta Bs Y”, usá
   search_products con category/brand/only_discount/max_price; no mandes
   todo el catálogo.
   Si no hay con descuento, la herramienta devuelve alternativas con
   fallback_without_discount=true: explicá que no hay promo y ofrecé esas
   opciones al precio normal. Si hace falta, usá get_best_sellers para
   ordenar por ventas reales; no inventes “más vendido”.
   Si el producto trae promo_price, ese es el precio final y promo_discount_percent
   el descuento; no uses el precio base.
   Si la ficha trae `price_note`, usala para explicar precio de lista vs precio
   vigente. Si `is_promotion` es false y `final_price` es mayor que
   `base_price`, NO lo llames descuento ni promoción: decí que es un precio
   especial vigente superior al de lista.
   Si trae quantity_tiers, mencioná que el precio especial aplica para esa
   cantidad exacta (“por 3 unidades, Bs X”) y preguntá cuántas quiere; no
   prometas un escalón que no esté en la lista ni lo interpretes como “desde X”.
   Si el catálogo nativo está activo y pide ver productos, usá show_catalog
   con esos filtros y no repitas la lista en el texto.
3. Si preguntan por promociones, ofertas o descuentos, usa list_promotions y
   menciona el descuento y la vigencia.
4. Si el cliente quiere varias unidades, usa get_product con quantity para ver
   el descuento por cantidad y sugiérele el escalón si conviene.
   Si pide quitar un producto, cambiar cantidad o vaciar el carrito, usá
   remove_from_cart, update_cart_quantity o clear_cart. No inventes que lo
   hiciste: confirmá con el resultado de la herramienta.
5. Ofrece un complemento o una tienda con stock; no empujes de más.
6. Cierra con una pregunta simple: "¿Te lo agrego?", "¿Lo vemos en Tienda 1?".

Onboarding:
- Primero respondé lo que el cliente preguntó; no empieces pidiendo datos.
- Si no tenés historial y la conversación va a recomendación personalizada o
  compra, después de dar valor preguntá: "¿Ya compraste antes en ROHO?".
- Si dice que sí, pedile el carnet o NIT y explicá que lo usás solo para buscar
  su historial. Usá identify_customer(consent=true).
- Si hay un candidato, confirmá el nombre y luego usá link_customer(consent=true).
  Usá el card_code que devolvió identify_customer; nunca inventes uno.
- Si no quiere dar el dato, no insistas: seguí con preguntas de preferencia.
- Nunca pidas carnet al inicio, para una consulta de precio/stock, ni lo repitas
  completo en la respuesta.

Memoria:
- Si tienes perfil o datos recordados, úsalos y no vuelvas a preguntar lo mismo.
- Si el cliente cuenta una preferencia estable (ciudad, estilo, talla, ocasión),
  pregúntale si puedes recordarla. No digas "anotado" ni "guardado" hasta que
  acepte; luego usa remember_customer_fact(consent=true).
- Pide los datos de a uno y explica para qué sirven.
- No pidas carnet, tarjeta ni datos sensibles en el chat.

Historial:
- Si el cliente pregunta qué compró, cuántas compras hizo o cuánto gastó,
  usa get_purchase_history.
- Usa get_customer_analysis para segmento, ticket promedio, frecuencia y
  recencia; adaptá la recomendación (nuevo, recurrente, alto valor, en riesgo).
- Para recomendar según lo que ya compró, usa recommend_for_customer y explica
  el motivo ("ya llevaste algo de esta categoría", "es recompra").
- Si no hay historial, no inventes: pregunta por su necesidad.

Conocimiento:
- Para envíos, garantías, devoluciones, horarios, direcciones, formas de pago
  o políticas, usá search_knowledge.
- Si no hay artículos publicados, decí que no tenés la información confirmada
  y ofrecé derivar con un asesor. No inventes políticas ni plazos.

Feedback:
- No preguntes al inicio ni antes de resolver la necesidad.
- Si la memoria trae “Encuesta pendiente”, hacé UNA sola pregunta post-entrega
  y llamá a record_feedback con el order_number.
- Si no quiere responder, usá skip_feedback y no insistas.
- Después de confirmar un pedido/pago, o si el cliente menciona una compra o
  entrega, podés hacer UNA pregunta opcional: atención (1-5), si el producto
  cumplió o si la entrega llegó a tiempo.
- Si hay un reclamo, agradecé, ofrecé solución o human_handoff y guardalo con
  record_feedback (type=complaint).
- No preguntes dos veces por el mismo pedido ni inventes reseñas.

Reglas:
- Usa SIEMPRE las herramientas para precio, stock, descuentos y pedidos.
- Nunca inventes promociones, descuentos, stock ni plazos.
- No prometas descuentos que no estén en SAP ni crees urgencia falsa.
- No inventes reseñas, testimonios ni “más vendido” sin datos.
- Si no hay promoción, dilo y ofrece una alternativa.
- No pidas tarjeta ni datos bancarios. El pago es por QR/link.
- Si el cliente se molesta o pide algo complejo, usa human_handoff.
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

    async def dispatch(self, name: str, arguments: dict) -> dict:
        method = getattr(self, f"tool_{name}", None)
        if method is None:
            return {"ok": False, "error": f"Herramienta desconocida: {name}"}
        try:
            return await method(**arguments)
        except TypeError as exc:
            return {"ok": False, "error": f"Argumentos inválidos: {exc}"}
        except Exception as exc:  # noqa: BLE001 - el LLM debe recibir el error
            logger.exception("Error en herramienta %s", name)
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _product(item) -> dict:
        return {
            "sku": item.sku,
            "name": item.name,
            "price": str(item.price),
            "currency": item.currency,
            "stock": item.stock,
            "category": getattr(item, "category", None),
            "brand": getattr(item, "brand", None),
        }

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

    async def tool_search_products(
        self,
        query: str | None = None,
        limit: int = 5,
        category: str | None = None,
        brand: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        only_discount: bool = False,
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
        self.last_search = {
            "products": products,
            "fallback_without_discount": fallback,
        }
        return {
            "ok": True,
            "products": products,
            "fallback_without_discount": fallback,
            "filters": {
                "query": query,
                "category": category,
                "brand": brand,
                "min_price": min_price,
                "max_price": max_price,
                "only_discount": only_discount,
            },
        }

    async def tool_show_catalog(
        self,
        query: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        only_discount: bool = False,
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
        return {"ok": True, "product": offer.as_dict()}

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
        return await purchases.get_history(
            self.session, self.contact_id, limit=limit
        )

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
        self, category: str | None = None, limit: int = 5
    ) -> dict:
        products = await sales_stats.best_sellers(
            self.session, category=category, limit=limit
        )
        return {
            "ok": True,
            "products": products,
            "note": None if products else "Todavía no hay estadísticas de ventas.",
        }

    async def tool_search_knowledge(self, query: str) -> dict:
        articles = knowledge.search(query, limit=3)
        return {
            "ok": True,
            "articles": articles,
            "note": None
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
            return {"ok": False, "error": str(exc)}
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
CHECKOUT_RE = re.compile(
    r"\b(confirm(?:o|ar|a|á)|genera(?:r|me)?\s+(?:el\s+)?(?:qr|link)|"
    r"link\s+de\s+pago|pagar|checkout)\b",
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
    r"colch[oó]n|cama|refri|refrigerador|heladera|nevera|lavadora|"
    r"secadora|microondas|televisor|tv|l[aá]mpara|foco|ducha|"
    r"grifer[ií]a|pintura|taladro|herramienta|maceta|jard[ií]n)\b",
    re.IGNORECASE,
)


class Agent:
    def __init__(self, wa: WhatsAppClient | None = None):
        self.wa = wa
        self._client: AsyncOpenAI | None = None

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

    async def _search_reply(
        self,
        session: AsyncSession,
        contact: Contact,
        query: str,
        *,
        limit: int = 5,
        min_price: float | None = None,
        max_price: float | None = None,
    ) -> AgentReply:
        await self._remember_query(session, contact, query)
        toolbox = Toolbox(session, contact, self.wa)
        result = await toolbox.tool_search_products(
            query=query,
            limit=limit,
            min_price=min_price,
            max_price=max_price,
        )
        products = result.get("products") or []
        if not products:
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text=persona.no_results(),
                        buttons=[
                            {"id": "catalog", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )
        return AgentReply(
            [
                Outbound(text=persona.search_intro()),
                self._search_list(products),
                Outbound(
                    kind="buttons",
                    text="¿Seguimos con algo más?",
                    buttons=self._search_buttons(),
                ),
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
                            f"No encontré stock en {label}. "
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
                            f" · stock {product.get('stock', 0)}"
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
        stock = sum((product.get("stock_by_store") or {}).values())
        lines = [
            f"*{product['name']}*",
            f"Precio: *Bs {product['final_price']}*",
        ]
        if product["discount_percent"] not in {"0", "0.0", "0.00"}:
            lines.append(
                f"Antes Bs {product['base_price']} "
                f"(-{product['discount_percent']}%)"
            )
        if product.get("period_to"):
            lines.append(f"Vigente hasta {product['period_to']}")
        if product.get("tier_quantity"):
            lines.append(
                f"Precio especial por {product['tier_quantity']} unidades"
            )
        lines.append(f"Stock: {stock}")
        buttons = [
            {"id": "catalog", "title": "Otra opción"},
            {"id": "human", "title": "Asesor"},
        ]
        if stock > 0:
            buttons.insert(
                0,
                {"id": f"add:{product['sku']}:1", "title": "Agregar 1"},
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
            Outbound(kind="buttons", text="\n".join(lines), buttons=buttons)
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
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=persona.added(
                        result.get("name") or sku,
                        f"{Decimal(result['cart_total']):,.2f}",
                    ),
                    buttons=[
                        {"id": "cart", "title": "Mi carrito"},
                        {"id": "catalog", "title": "Seguir comprando"},
                    ],
                )
            ]
        )

    @staticmethod
    def _search_list(products: list[dict]) -> Outbound:
        rows = []
        for product in products[:9]:
            price = product.get("promo_price") or product.get("price")
            rows.append(
                {
                    "id": f"product:{product['sku']}",
                    "title": Agent._truncate(product["name"], 24),
                    "description": (
                        f"Bs {price} · stock {product.get('stock', 0)}"
                    )[:72],
                }
            )
        return Outbound(
            kind="list",
            text="Elegí una opción para ver precio, foto y stock:",
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

    async def handle(
        self,
        session: AsyncSession,
        contact: Contact,
        text: str,
        history: list[dict] | None = None,
        memory: str | None = None,
    ) -> AgentReply:
        normalized = (text or "").strip().lower()
        raw = (text or "").strip()
        simple = re.sub(
            r"[^a-záéíóúñü ]", " ", normalized
        ).strip()
        simple = re.sub(r"\s+", " ", simple)
        toolbox = Toolbox(session, contact, self.wa)

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
                            {"id": "explore", "title": "Ver categorías"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        if normalized == "cart":
            result = await toolbox.tool_view_cart()
            lines = ["Tu carrito:"]
            for item in result["items"]:
                lines.append(
                    f"- *{item['name']}* x{item['quantity']} — "
                    f"Bs {Decimal(item['line_total']):,.2f}"
                )
            if not result["items"]:
                lines.append("Está vacío.")
            else:
                lines.append(f"Total: *Bs {Decimal(result['total']):,.2f}*")
            return AgentReply(
                [
                    Outbound(
                        kind="buttons",
                        text="\n".join(lines),
                        buttons=[
                            {"id": "catalog", "title": "Seguir comprando"},
                            {"id": "human", "title": "Asesor"},
                        ],
                    )
                ]
            )

        if normalized == "human":
            await toolbox.tool_human_handoff("El cliente pidió un asesor")
            return AgentReply(
                [
                    Outbound(
                        text=persona.handoff()
                    )
                ]
            )

        if CLEAR_CART_RE.search(raw):
            return await self._clear_cart_reply(session, contact)

        if STATUS_RE.search(raw):
            return await self._status_reply(session, contact)

        if CHECKOUT_RE.search(raw) and normalized not in {
            "formas de pago",
            "medios de pago",
        }:
            return await self._checkout_reply(session, contact)

        if SEARCH_RE.search(raw):
            return await self._search_reply(session, contact, raw)

        if normalized.startswith("cat:"):
            category = raw.split(":", 1)[1].strip()
            return await self._product_list(session, contact, category)

        if normalized.startswith("product:"):
            sku = raw.split(":", 1)[1].strip()
            return await self._product_detail(session, contact, sku)

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
        if not settings.deepseek_api_key:
            return await self._demo(session, contact, text)
        try:
            return await self._llm_handle(
                session, contact, text, history or [], memory
            )
        except Exception:  # noqa: BLE001 - fallback para no dejar al cliente sin respuesta
            logger.exception("Fallo el agente LLM; se usa el modo demo")
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
                f"(-{promo['discount_percent']}%), hasta {valid}, "
                f"stock {promo.get('stock', 0)}."
            )
        return "\n".join(lines)

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
        promo_context = await self._promotion_preflight(text, toolbox)
        if promo_context:
            messages.append({"role": "system", "content": promo_context})
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": text})

        for _ in range(4):
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
            choice = completion.choices[0].message
            if not choice.tool_calls:
                answer = (choice.content or "").strip()
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
                        outbound.append(self._search_list(products))
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
                return AgentReply(outbound)

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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        return AgentReply(
            [Outbound(text="No pude completar la consulta. ¿Te derivo con un asesor?")]
        )

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
                f"\n   SKU: {product['sku']} · stock: {product['stock']}"
            )
        lines.append(
            "\nPara agregar: escribe *agregar* seguido del SKU y la cantidad "
            "(ej. *agregar SKU 2*)."
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
