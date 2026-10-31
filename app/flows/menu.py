"""Menú: categorías, listas por ambiente e ideas de regalo.

Extraído de `agent.py` para que el enrutamiento no crezca.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact
from ..replies import AgentReply
from ..services import ideas as ideas_service
from ..whatsapp import Outbound


async def categories(agent, session: AsyncSession, contact: Contact) -> AgentReply:
    """Lista de ambientes para arrancar la conversación."""
    from ..agent import FRIENDLY_CATEGORIES, Toolbox, persona

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
                                "title": agent._truncate(row["label"], 24),
                                "description": row["label"],
                            }
                            for row in FRIENDLY_CATEGORIES
                        ],
                    }
                ],
            )
        ]
    )



def _formato_precio(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")


async def product_list(
    agent,
    session: AsyncSession,
    contact: Contact,
    category: str,
    termino: str = "",
    directo: bool = False,
) -> AgentReply:
    """Productos de un ambiente, ordenados por lo esperado."""
    from ..agent import (
        CATEGORY_ORDER,
        FRIENDLY_CATEGORIES,
        Toolbox,
        _ordenar_por_ambiente,
    )

    key = category.strip().lower()
    friendly = next(
        (row for row in FRIENDLY_CATEGORIES if row["key"] == key),
        None,
    )
    canonical = friendly["category"] if friendly else category
    label = friendly["label"] if friendly else category
    toolbox = Toolbox(session, contact, agent.wa)
    products: list[dict] = []
    # Para un ambiente se busca por lo que se espera ver (sofá, mesa...) y
    # no por la categoría entera, que traía espejos primero.
    # Preguntar antes de listar, pero solo si el catálogo lo justifica:
    # si las opciones devuelven lo mismo, preguntar confunde.
    if not termino and not directo:
        from ..services import categorias

        guia = categorias.pregunta(key)
        if guia is not None:
            utiles = []
            vistos: set[str] = set()
            for etiqueta, busqueda in guia["opciones"]:
                encontrados = await toolbox.tool_search_products(
                    category=canonical, query=busqueda, limit=6
                )
                nuevos = [
                    producto
                    for producto in encontrados.get("products") or []
                    if producto["sku"] not in vistos
                ]
                if nuevos:
                    utiles.append((etiqueta, busqueda))
                    vistos.update(p["sku"] for p in nuevos)
            if len(utiles) >= 2 and len(vistos) >= 8:
                agent._trace(f"Pregunta de categoría: {key}")
                return AgentReply(
                    [
                        Outbound(
                            kind="list",
                            text=(
                                f"{guia['texto']}\n"
                                "Así te muestro justo lo que necesitás 👇"
                            ),
                            button_text="Elegir",
                            sections=[
                                {
                                    "title": "Opciones",
                                    "rows": categorias.opciones(
                                        key, utiles
                                    ),
                                }
                            ],
                        )
                    ]
                )

    terminos = (termino,) if termino else CATEGORY_ORDER.get(key, ())[:5]
    for termino_actual in terminos:
        encontrados = await toolbox.tool_search_products(
            category=canonical, query=termino_actual, limit=2 if termino else 2
        )
        for producto in encontrados.get("products") or []:
            if all(
                producto["sku"] != previo["sku"] for previo in products
            ):
                products.append(producto)
        if len(products) >= 9:
            break
    if not products:
        result = await toolbox.tool_search_products(
            category=canonical, limit=12
        )
        products = _ordenar_por_ambiente(
            result.get("products") or [], key
        )
    products = products[:9]
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
            "title": "Opciones",
            "rows": [
                {
                    "id": f"product:{product['sku']}",
                    "title": agent._truncate(product["name"], 24),
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
    from ..services import emoji

    # Una sola respuesta: los productos van en el menú, con su precio.
    # Antes se mandaba además un texto con la misma lista y se leía doble.
    precios = [
        float(producto.get("promo_price") or producto.get("price") or 0)
        for producto in products
    ]
    precios = [precio for precio in precios if precio > 0]
    icono = emoji.para(label)
    cantidad = len(products)
    if cantidad == 1:
        resumen = "tengo *1 opción*"
    else:
        resumen = f"tengo *{cantidad} opciones*"
    if precios:
        minimo = min(precios)
        resumen += f" desde *Bs {_formato_precio(minimo)}*"
    # Gancho de venta: la opción con mejor descuento, si hay.
    gancho = ""
    con_descuento = [
        producto
        for producto in products
        if str(producto.get("promo_discount_percent") or "").strip()
    ]
    if con_descuento:
        mejor = max(
            con_descuento,
            key=lambda producto: float(
                producto.get("promo_discount_percent") or 0
            ),
        )
        try:
            porcentaje = float(mejor["promo_discount_percent"])
        except (TypeError, ValueError):
            porcentaje = 0
        if porcentaje >= 15:
            gancho = (
                f"\nLa de mejor descuento: *"
                f"{agent._truncate(mejor['name'], 40)}* (−{porcentaje:.0f}%)."
            )
    texto = (
        f"{icono} *{label}*: {resumen}.{gancho}\n"
        "Tocá una para ver la foto y la ficha 👇"
    )
    return AgentReply(
        [
            Outbound(
                kind="list",
                text=texto,
                button_text="Ver productos",
                sections=sections,
            ),
        ]
    )



async def idea(agent, session: AsyncSession, contact: Contact, intent: dict) -> AgentReply:
    """Responde una idea ("distraer a las visitas") con opciones reales."""
    from ..agent import Toolbox, _idea_producto_valido

    """Responde una idea ("distraer a las visitas") con opciones reales."""
    toolbox = Toolbox(session, contact, agent.wa)
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
        *agent._search_cards(encontrados[:3]),
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

