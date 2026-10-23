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
    extra = f" Hoy es {holiday}, por si te sirve." if holiday else ""
    return (
        f"¡{greeting}{first_name(contact_name)}! 👋 Soy *{name()}*, "
        f"tu asesora de hogar en ROHO.{extra} "
        "Contame qué estás buscando y lo vemos con calma."
    )


def ask_need() -> str:
    return (
        "Contame qué necesitás: por ejemplo, un sofá para la sala, "
        "un colchón de 2 plazas o pintura para exterior."
    )


def search_intro() -> str:
    return (
        "Dale, mirá lo que encontré. "
        "Tocá una opción y te muestro foto y precio."
    )


def no_results() -> str:
    return (
        "Uy, eso no lo encontré. "
        "¿Probamos con otra palabra o te muestro las categorías?"
    )


def added(product_name: str, total: str) -> str:
    return (
        f"¡Listo! Agregué *{product_name}*.\n"
        f"Tu carrito va en *Bs {total}*."
    )


def cart_empty() -> str:
    return (
        "Tu carrito está vacío por ahora. "
        "Elegí un producto y te lo agrego."
    )


def cart_cleared() -> str:
    return (
        "Listo, vacié tu carrito. "
        "¿Buscamos algo nuevo o te muestro categorías?"
    )


def checkout_failed(reason: str) -> str:
    return (
        f"Uy, no pude cerrar el pedido: {reason}.\n"
        "No generé ningún cobro. ¿Querés que lo revise alguien del equipo?"
    )


def handoff() -> str:
    return (
        "Ya avisé a alguien del equipo para que revise este caso. "
        "Mientras tanto puedo seguir ayudándote con precios y opciones."
    )


def product_intro() -> str:
    return "Mirá esta opción 👀"


def categories_intro() -> str:
    return "¿Por dónde arrancamos? Elegí una categoría 👇"
