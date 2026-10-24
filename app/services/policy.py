"""Guardrails de política: lo que el bot no debe responder por su cuenta.

Salud, legal, financiero y datos sensibles se derivan: el bot no da consejos ni
pide información que no corresponde por chat.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

TOPICS: dict[str, tuple[str, ...]] = {
    "salud": (
        "que remedio", "qué remedio", "medicamento", "dosis", "diagnostico",
        "diagnóstico", "me duele", "tengo dolor", "estoy embarazada",
        "sirve para el dolor", "asma", "alergia", "cancer", "cáncer",
        "presion alta", "presión alta", "azucar en sangre",
    ),
    "legal": (
        "demandar", "abogado", "denuncia", "juicio", "ley de defensa",
        "defensa al consumidor", "hacer valer mis derechos",
    ),
    "financiero": (
        "sacar un credito", "sacar un crédito", "pedir un prestamo",
        "pedir un préstamo", "tasa de interes", "tasa de interés",
        "cuotas sin interes", "cuotas sin interés", "invertir mi plata",
        "no puedo pagar la deuda", "refinanciar",
    ),
    "datos": (
        "numero de tarjeta", "número de tarjeta", "cvv", "clave de la tarjeta",
        "clave de mi tarjeta", "mandame tu tarjeta", "pasame tu clave",
        "codigo de seguridad de la tarjeta", "código de seguridad de la tarjeta",
    ),
    "seguridad": (
        "instalacion electrica", "instalación eléctrica", "conexion de gas",
        "conexión de gas", "cortocircuito", "me electrocuto", "me quemo",
    ),
}

_TEXTS = {
    "salud": (
        "Eso no lo puedo resolver yo: no doy consejos de salud, ni siquiera "
        "sobre productos. Te paso con una persona del equipo que puede "
        "orientarte mejor."
    ),
    "legal": (
        "Eso es un tema legal y no puedo darte una respuesta por acá. Te paso "
        "con una persona del equipo para que te oriente."
    ),
    "financiero": (
        "No doy consejos financieros ni de crédito: te paso con una persona "
        "del equipo que puede explicarte las opciones reales."
    ),
    "datos": (
        "Por seguridad no pido ni recibo números de tarjeta, claves ni códigos "
        "por este chat. El pago se hace en el link o en la tienda. Si querés, "
        "te paso con una persona del equipo."
    ),
    "seguridad": (
        "Las instalaciones de gas o electricidad las tiene que revisar un "
        "técnico. No te doy instrucciones por chat para eso; te paso con "
        "alguien del equipo."
    ),
}


def detect(text: str | None) -> str | None:
    folded = (text or "").lower()
    for topic, phrases in TOPICS.items():
        if any(phrase in folded for phrase in phrases):
            return topic
    return None


def reply(topic: str) -> str:
    return _TEXTS.get(topic) or _TEXTS["legal"]
