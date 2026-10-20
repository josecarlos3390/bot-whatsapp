"""Objetos compartidos (cliente de WhatsApp y agente)."""

from .agent import Agent
from .whatsapp import WhatsAppClient

whatsapp = WhatsAppClient()
agent = Agent(whatsapp)
