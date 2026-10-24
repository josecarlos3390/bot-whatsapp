# Mejoras pendientes del bot

**Actualizado:** 24-oct-2026
**Criterio:** lo que falta para que el bot atienda bien con clientes reales. Se
ordena por impacto en el cliente, no por esfuerzo.

---

## P1 — Transcribir notas de voz

**Estado:** evaluado, no implementado. Decidido dejarlo para más adelante.

**Problema:** hoy un audio entrante se descarta (`Mensaje sin texto ignorado`).
El cliente manda una nota de voz y el bot no responde nada.

**Impacto en costos (medido):**

| Concepto | Costo |
|---|---|
| WhatsApp (recibir audio + responder texto en 24 h) | **$0** |
| DeepSeek por el texto transcrito (~150 tokens sobre 4.500) | ~$0,00004 por audio |
| Transcripción con Groq (whisper-large-v3-turbo) | ~$1,4/mes con 100 audios/día |
| Transcripción con OpenAI (whisper-1) | ~$9/mes con 100 audios/día |
| Transcripción local (whisper.cpp) | $0 (usa CPU del servidor) |

**Latencia:** +0,5-1,5 s (Groq), +2-4 s (OpenAI), +2-6 s (local).

**Decisión pendiente:** proveedor. Recomendación: Groq por velocidad y costo;
local si no se quiere sacar el audio del servidor.

**Alcance:**

1. Al recibir `type == "audio"`, descargar el media de Meta de inmediato (el
   enlace caduca en minutos).
2. Transcribir (OGG/Opus) y usar el texto como mensaje del cliente.
3. Si falla o dura más de 2 minutos: "No pude escuchar bien tu audio, ¿me lo
   escribís?".
4. Guardar la transcripción en el mensaje para auditoría.
5. Aviso de privacidad si se usa un proveedor externo.

**Criterios de aceptación:**

- Un audio de 30 s se responde en menos de 6 s.
- Si la transcripción falla, el cliente recibe una respuesta (nunca silencio).
- El costo de transcripción se ve en el panel.

---

## P2 — Políticas de negocio publicadas

**Problema:** envíos, garantías y devoluciones se responden desde 3 documentos
incompletos; el resto se deriva a un asesor.

**Falta:** documentos definitivos de envíos (costos, plazos, cobertura),
garantías por familia de producto y devoluciones/cambios.

**Impacto:** es la consulta más frecuente después del precio. Hoy genera
derivaciones evitables.

---

## P3 — Alertas al asesor

**Problema:** cuando el bot deriva, el aviso solo existe dentro de la consola.
Si nadie la mira, el caso duerme.

**Falta:** un destino (bot de Telegram o URL de webhook). El código ya lo
soporta (`HANDOFF_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

**Impacto:** alto en percepción de servicio; esfuerzo bajo.

---

## P4 — Cerrar el ciclo comercial

**Problema:** el embudo llega a checkout y se corta: en modo VTEX informativo no
se crean pedidos ni pagos, así que no hay postventa ni seguimiento.

**Depende de:** integración de pedidos/pagos con VTEX o SAP.

**Impacto:** sin esto no se puede medir conversión real ni hacer
"¿cómo te fue con tu compra?".

---

## P5 — Canal avanzado (depende de Meta)

- Plantillas: aviso de stock, estado de pedido, encuesta post-entrega.
- Catálogo nativo y mensajes de producto (requiere número business y catálogo
  aprobado).
- WhatsApp Flows para cotizaciones o datos de envío.

---

## P6 — Aprendizaje con el equipo

- Convertir conversaciones reales flojas en casos de prueba fijos
  (`tests/test_conversations.py`).
- Botón en la consola para marcar una respuesta como "buena/mala" y alimentar
  ese set.
- Revisión semanal del panel de calidad.

---

## Mejoras ya implementadas (referencia)

Para no volver a proponerlas: clasificador de intención (reglas + modelo),
empatía ante temas delicados, derivación por enojo, guardrails de política
(salud/legal/dinero/datos), identidad y despedida, detección de charla nueva y
cambio de rubro, memoria de preferencias, validación de salida (precios, SKU,
frases prohibidas), respaldo si falla el modelo, medición de latencia y tokens,
control de calidad con trazas, simuladores de reglas y ocasiones en el panel.
