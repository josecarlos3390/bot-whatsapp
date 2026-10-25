"""Simula conversaciones con clientes y evalúa las respuestas.

Un modelo hace de cliente (con un objetivo) y otro evalúa el resultado. Sirve
para encontrar combinaciones que a un humano no se le ocurren, sin usar
WhatsApp real ni ensuciar datos.

Uso:
    python -m scripts.fuzz_conversations --conversaciones 5 --turnos 6
    python -m scripts.fuzz_conversations --solo-reglas    # sin costo de modelo

Cada conversación usa un contacto temporal que se borra al terminar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import delete

from app.agent import Agent
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    CustomerProfile,
    FunnelEvent,
    Handoff,
    Message,
)

PERSONAS = [
    "Busco un colchón de 2 plazas, con presupuesto ajustado.",
    "Quiero un televisor de 50 pulgadas; si hay OLED, mejor.",
    "Pregunto por el envío a Santa Cruz y los plazos.",
    "Necesito algo para regalar en un cumpleaños, no sé qué.",
    "Quiero comparar dos licuadoras y saber cuál conviene.",
    "Consulto la garantía de una lavadora.",
    "Tengo un problema con un pedido anterior y estoy molesto.",
    "Quiero amueblar un living chico con poco presupuesto.",
]

JUEZ = """Eres un evaluador de calidad de un chatbot de ventas.
Te paso una conversación entre un cliente y el bot. Evalúa SOLO el desempeño del bot.

Devuelve JSON con este formato exacto:
{"nota": 1-5, "problemas": ["..."], "correcto": true|false}

Criterios:
- Responde lo que el cliente preguntó (no otro tema).
- No inventa productos, precios ni plazos.
- No repite frases ni se traba.
- Ofrece un siguiente paso claro.
- Si el cliente está molesto o cuenta algo delicado, responde con empatía.
"""


async def _cliente_habla(cliente: AsyncOpenAI, persona: str, historial: list[str]) -> str:
    mensajes = [
        {
            "role": "system",
            "content": (
                "Sos un cliente que escribe por WhatsApp a un homecenter. "
                f"Tu objetivo: {persona}\n"
                "Escribí un solo mensaje corto, como lo haría una persona real "
                "(sin comillas, sin explicaciones)."
            ),
        }
    ]
    for linea in historial[-6:]:
        mensajes.append({"role": "user", "content": linea})
    respuesta = await cliente.chat.completions.create(
        model=settings.deepseek_model,
        messages=mensajes,
        temperature=0.7,
        max_tokens=80,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return (respuesta.choices[0].message.content or "").strip().strip('"')


async def _evalua(cliente: AsyncOpenAI, transcripcion: str) -> dict:
    respuesta = await cliente.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": JUEZ},
            {"role": "user", "content": transcripcion},
        ],
        temperature=0,
        max_tokens=300,
        extra_body={"thinking": {"type": "disabled"}},
    )
    texto = respuesta.choices[0].message.content or "{}"
    try:
        inicio = texto.find("{")
        return json.loads(texto[inicio:]) if inicio >= 0 else {}
    except ValueError:
        return {}


async def _limpiar(session, contact_id: str, conversation_id: str) -> None:
    await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await session.execute(
        delete(Handoff).where(Handoff.conversation_id == conversation_id)
    )
    await session.execute(
        delete(FunnelEvent).where(FunnelEvent.contact_id == contact_id)
    )
    await session.execute(
        delete(CustomerProfile).where(CustomerProfile.contact_id == contact_id)
    )
    await session.execute(
        delete(Conversation).where(Conversation.id == conversation_id)
    )
    await session.execute(delete(Contact).where(Contact.id == contact_id))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversaciones", type=int, default=5)
    parser.add_argument("--turnos", type=int, default=6)
    parser.add_argument("--solo-reglas", action="store_true")
    args = parser.parse_args()

    cliente = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    resultados: list[dict] = []

    async with SessionLocal() as session:
        for indice in range(args.conversaciones):
            persona = random.choice(PERSONAS)
            sufijo = uuid.uuid4().hex[:10]
            contact = Contact(
                wa_id=f"fuzz{sufijo}",
                phone_e164=f"+{sufijo[:9]}",
                name="Fuzz",
            )
            session.add(contact)
            await session.flush()
            conversation = Conversation(contact_id=contact.id)
            session.add(conversation)
            await session.commit()

            historial: list[str] = []
            agente = Agent()
            print(f"\n=== Conversación {indice + 1}: {persona}")
            for turno in range(args.turnos):
                if args.solo_reglas:
                    texto = persona if turno == 0 else "¿y qué más tenés?"
                else:
                    texto = await _cliente_habla(cliente, persona, historial) if turno else await _cliente_habla(cliente, persona, [])
                if not texto:
                    break
                historial.append(f"Cliente: {texto}")
                respuesta = await agente.handle(session, contact, texto)
                # Igual que en producción: el postproceso evita repeticiones.
                respuesta = await agente.postprocess(
                    session, contact, texto, respuesta
                )
                salida = " ".join(m.text or "" for m in respuesta.messages)
                historial.append(f"Bot: {salida[:400]}")
                print(f"  C: {texto[:110]}")
                print(f"  B: {salida.replace(chr(10), ' ')[:150]}")

            transcripcion = "\n".join(historial)
            evaluacion = (
                {"nota": 0, "problemas": ["sin evaluar (modo reglas)"], "correcto": False}
                if args.solo_reglas
                else await _evalua(cliente, transcripcion)
            )
            resultados.append(
                {
                    "persona": persona,
                    "nota": evaluacion.get("nota"),
                    "correcto": evaluacion.get("correcto"),
                    "problemas": evaluacion.get("problemas"),
                    "transcripcion": transcripcion,
                }
            )
            print(f"  >> nota {evaluacion.get('nota')} | problemas: {evaluacion.get('problemas')}")
            await _limpiar(session, contact.id, conversation.id)

    salida = Path(".tools/fuzz-report.json")
    salida.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    notas = [r["nota"] for r in resultados if isinstance(r["nota"], (int, float))]
    print("\n--- resumen ---")
    print(f"conversaciones: {len(resultados)}")
    if notas:
        print(f"nota promedio: {sum(notas) / len(notas):.2f}")
    print(f"informe: {salida}")


if __name__ == "__main__":
    asyncio.run(main())
