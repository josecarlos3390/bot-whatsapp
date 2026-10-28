"""Respuesta del agente, independiente del canal.

Vive fuera de `agent.py` para que los flujos puedan devolver respuestas sin
importar el módulo de enrutamiento (que los importa a ellos).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .whatsapp import Outbound


@dataclass
class AgentReply:
    messages: list[Outbound] = field(default_factory=list)
