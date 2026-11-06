"""WhatsApp Flows: formularios nativos dentro del chat.

El cliente completa una pantalla de WhatsApp (sin salir de la app) y la
respuesta llega como `interactive.nfm_reply` con un JSON. Acá se interpreta,
se guarda y se responde.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Campos que puede traer el formulario.
CAMPOS = ("nombre", "direccion", "referencia", "documento")

# El Flow publicado para capturar los datos de entrega.
FLOW_DATOS_ENTREGA = "2134798617126043"


def es_respuesta(texto: str) -> bool:
    """¿El texto es el JSON que devuelve un Flow?"""
    valor = (texto or "").strip()
    if not valor.startswith("{") or not valor.endswith("}"):
        return False
    try:
        datos = json.loads(valor)
    except ValueError:
        return False
    return isinstance(datos, dict) and any(campo in datos for campo in CAMPOS)


def leer(texto: str) -> dict[str, str]:
    """Devuelve solo los campos conocidos, limpios."""
    try:
        datos = json.loads(texto)
    except ValueError:
        return {}
    if not isinstance(datos, dict):
        return {}
    limpio: dict[str, str] = {}
    for campo in CAMPOS:
        valor = datos.get(campo)
        if isinstance(valor, str) and valor.strip():
            limpio[campo] = valor.strip()[:300]
    return limpio


def confirmacion(datos: dict[str, str]) -> str:
    """Mensaje que confirma los datos recibidos."""
    lineas = ["✅ ¡Gracias! Guardé tus datos de entrega:", ""]
    if datos.get("nombre"):
        lineas.append(f"👤 {datos['nombre']}")
    if datos.get("direccion"):
        lineas.append(f"📍 {datos['direccion']}")
    if datos.get("referencia"):
        lineas.append(f"🧭 {datos['referencia']}")
    if datos.get("documento"):
        lineas.append(f"🧾 Documento: {datos['documento']}")
    return "\n".join(lineas)


def mensaje_pedir_datos(token: str = "") -> dict:
    """Payload del mensaje interactivo que abre el formulario."""
    return {
        "messaging_product": "whatsapp",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Datos de entrega"},
            "body": {
                "text": (
                    "Completá tus datos y coordinamos la entrega del pedido 👇"
                )
            },
            "footer": {"text": "ROHO Homecenter"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_id": FLOW_DATOS_ENTREGA,
                    "flow_cta": "Completar datos",
                    "flow_action": "navigate",
                    "flow_action_payload": {"screen": "DATOS"},
                    **({"flow_token": token} if token else {}),
                },
            },
        },
    }
