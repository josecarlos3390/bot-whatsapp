"""Voz y microcopy de Rohi, la asesora virtual de ROHO."""

from __future__ import annotations

from . import context
from .config import settings


def name() -> str:
    return settings.bot_name or "Rohi"


def first_name(contact_name: str | None) -> str:
    value = (contact_name or "").strip().split(" ")[0]
    return f" {value}" if value else ""


def welcome(contact_name: str | None = None) -> str:
    greeting = context.greeting()
    holiday = context.holiday_today()
    extra = f" Hoy es {holiday}." if holiday else ""
    return (
        f"¡{greeting}{first_name(contact_name)}! 👋 Soy *{name()}*, "
        f"tu asesora de hogar en ROHO.{extra} "
        "Contame qué estás buscando y te ayudo a encontrar lo mejor."
    )


def ask_need() -> str:
    return (
        "Decime qué necesitás, por ejemplo: "
        "“un sofá para la sala”, “un colchón de 2 plazas” "
        "o “pintura para exterior”."
    )


def search_intro() -> str:
    return (
        "¡Dale! 🙌 Encontré estas opciones para vos. "
        "Tocá una y te muestro foto, precio y stock."
    )


def no_results() -> str:
    return (
        "Uy, no encontré eso 😅. "
        "¿Probamos con otra palabra o te muestro las categorías?"
    )


def added(product_name: str, total: str) -> str:
    return (
        f"¡Buenísimo! 🛒 Agregué *{product_name}*.\n"
        f"Tu carrito va en *Bs {total}*."
    )


def cart_empty() -> str:
    return (
        "Tu carrito está vacío por ahora 🛒. "
        "Elegí un producto y te lo agrego."
    )


def cart_cleared() -> str:
    return (
        "Listo, vacié tu carrito 🧹. "
        "¿Buscamos algo nuevo o querés que te muestre categorías?"
    )


def checkout_failed(reason: str) -> str:
    return (
        f"Uf, no pude cerrar el pedido 😕: {reason}.\n"
        "No generé ningún cobro. ¿Querés que lo revise una persona del equipo?"
    )


def handoff() -> str:
    return (
        "Listo, te paso con alguien del equipo 🙋. "
        "Te va a responder por este mismo chat lo antes posible."
    )


def product_intro() -> str:
    return "Mirá esta opción 👀"


def categories_intro() -> str:
    return "¿Por dónde arrancamos? Elegí una categoría 👇"
