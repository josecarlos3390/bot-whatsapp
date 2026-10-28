"""Voz y microcopy de Rohi, la asesora virtual de ROHO."""

from __future__ import annotations

from . import context
from .config import settings


def name() -> str:
    return settings.bot_name or "Rohi"


def first_name(contact_name: str | None) -> str:
    value = (contact_name or "").strip().split(" ")[0]
    return f" {value}" if value else ""


# Variantes del saludo: mismo formato, distinta frase, para no repetirse.
_VARIANTES_SALUDO = (
    "¿Qué necesitás hoy? Podés escribirme directamente o elegir una opción 👇",
    "¿En qué te doy una mano hoy? Escribime o tocá una opción 👇",
    "¿Qué estás buscando hoy? Contame o elegí una opción 👇",
)


def welcome(contact_name: str | None = None) -> str:
    """Saludo principal: nombre, quién es y tres opciones."""
    import random

    nombre = first_name(contact_name).strip()
    saludo = f"¡Hola, {nombre}! 👋" if nombre else "¡Hola! 👋"
    variante = random.choice(_VARIANTES_SALUDO)
    return (
        f"{saludo} Soy *{name()}*, tu asesora virtual de ROHO Homecenter. 🏡\n"
        "Estoy acá para ayudarte a encontrar productos y resolver tus "
        f"consultas.\n{variante}"
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


def handoff_queued(office_open: bool = True) -> str:
    """Aviso cuando no hay asesor conectado con lugar."""
    if not office_open:
        return (
            "Estamos fuera del horario de atención (lunes a viernes, 9 a 18). "
            "Dejé tu caso registrado y te contactan al abrir.\n\n"
            "Mientras tanto, puedo ayudarte con productos, precios o stock."
        )
    return (
        "En este momento los asesores están ocupados. Dejé tu caso en cola y "
        "te asignamos uno en cuanto se libere.\n\n"
        "Mientras tanto, puedo seguir ayudándote con productos, precios o stock."
    )


def empathy(topic: str | None = None, closing: bool = False) -> str:
    """Respuesta ante un tema delicado: empatía, sin vender."""
    if closing:
        return (
            "Gracias por contármelo. 💙 Quedo por acá si en algún momento "
            "necesitás algo de la casa."
        )
    if topic == "duelo":
        return (
            "Lamento mucho lo que me contás. 😔 Perder a alguien que querés "
            "—una mascota también es familia— es muy duro.\n\n"
            "Te soy sincero: yo estoy acá para ayudarte con cosas del hogar, "
            "así que no soy la mejor compañía para acompañarte en esto. Si "
            "querés, te paso con una persona del equipo; y cuando quieras "
            "retomamos lo que necesites."
        )
    if topic == "salud":
        return (
            "Siento mucho que estés pasando por eso. 😔\n\n"
            "Yo no soy quien para darte consejos de salud, pero sí puedo "
            "escucharte un momento. Si preferís hablar con una persona del "
            "equipo, te paso; y cuando quieras seguimos con lo que necesites "
            "de la casa."
        )
    return (
        "Qué mal que estés así. 😔 Si querés contarme qué pasó, te escucho.\n\n"
        "También te digo: estoy acá para ayudarte con cosas del hogar, así que "
        "si preferís hablar con una persona del equipo, te paso."
    )


def frustration() -> str:
    """Cliente enojado o esperando: disculpa corta y derivación inmediata."""
    return (
        "Tenés razón en enojarte y te pido disculpas. 🙏\n\n"
        "Ya avisé a una persona del equipo para que tome tu caso y te "
        "responda por acá. Para adelantarle el trabajo, ¿me contás en una "
        "frase qué pasó?"
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
