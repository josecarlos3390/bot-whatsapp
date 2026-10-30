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



async def product_list(
    agent, session: AsyncSession, contact: Contact, category: str
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
    for termino in CATEGORY_ORDER.get(key, ())[:5]:
        encontrados = await toolbox.tool_search_products(
            category=canonical, query=termino, limit=2
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
    # Primero el texto con nombre y precio; después el menú para elegir.
    # Antes llegaba solo el menú y el cliente no veía qué había.
    lineas = []
    for index, producto in enumerate(products[:9], start=1):
        precio = producto.get("promo_price") or producto.get("price")
        linea = f"{index}. {agent._truncate(producto['name'], 52)} — Bs {precio}"
        if producto.get("brand"):
            linea += f" · {producto['brand']}"
        lineas.append(linea)
    from ..services import emoji

    icono = emoji.para(label)
    texto = (
        f"En *{label}* tengo estas opciones {icono}:\n\n"
        + "\n".join(lineas)
        + "\n\nElegí una y te muestro la foto y la ficha completa 👇"
    )
    return AgentReply(
        [
            Outbound(text=texto[:4096]),
            Outbound(
                kind="list",
                text="Tocá una opción para ver la foto y la ficha 👇",
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

