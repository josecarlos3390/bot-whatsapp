# Capa de canales: el mismo bot en WhatsApp, Instagram, Messenger y web

Diseño técnico para que el bot atienda en más de un canal sin duplicar el
cerebro (catálogo, reglas, IA, aprendizaje, derivación y KPIs).

## 1. Objetivo

Que un mensaje que llega por cualquier canal:

1. se normalice a una estructura común,
2. pase por **el mismo agente**,
3. se traduzca al formato que ese canal entiende,
4. quede registrado igual para la consola, los KPIs y la auditoría.

No objetivo: reescribir el bot. El agente ya produce mensajes estructurados.

## 2. Estado actual y acoplamiento

| Pieza | Estado |
|---|---|
| `AgentReply` / `Outbound` | Ya son genéricos (texto, imagen, botones, lista) |
| Envío real | `whatsapp.send()` en `app/services/ingest.py` (un solo punto) |
| Referencias a `WhatsAppClient` | 10 en todo el proyecto |
| Contacto | Se identifica por `wa_id` (acopla a WhatsApp) |

Lo único realmente atado al canal es **la identidad del contacto** y el
**envío**.

## 3. Arquitectura

```
Instagram ─┐
Messenger ─┼→ router de webhooks ─→ Inbound ─→ agente (sin cambios)
Web chat  ─┤                                      │
WhatsApp  ─┘                                      ▼
                                        render(reply, capacidades)
                                                  │
                                                  ▼
                                        adaptador del canal
```

### Interfaces (`app/channels/base.py`)

```python
@dataclass(frozen=True)
class Capabilities:
    name: str
    lists: bool = False      # listas de WhatsApp
    buttons: int = 0         # botones o respuestas rápidas
    images: bool = True
    markdown: str = "plain"  # whatsapp | markdown | html | plain
    max_text: int = 2000

@dataclass
class Inbound:
    channel: str
    external_id: str
    text: str = ""
    name: str | None = None
    media: dict | None = None
    raw: dict = field(default_factory=dict)
```

### Traducción (`app/channels/render.py`)

`render(mensaje, capacidades) -> list[Rendered]` resuelve las diferencias:

| Caso | WhatsApp | Instagram / Messenger | Web chat |
|---|---|---|---|
| `list` | Lista nativa | **Opciones numeradas en texto** | Lista o tarjetas |
| `buttons` | Hasta 3 | Hasta 3 (respuestas rápidas) | Libre |
| `*negrita*` | Se conserva | Se quita | Se conserva |
| Imagen | Foto | Foto | Foto |
| Texto largo | 4.096 | 1.000 | 4.000 |

Regla de oro: **si el canal no soporta algo, se degrada a texto numerado**,
nunca se pierde la información.

## 4. Modelo de datos

### Cambio en `contacts`

```python
channel: str = "whatsapp"                 # whatsapp | instagram | messenger | webchat
external_id: str = ""                     # wa_id, IGSID, PSID o session_id
wa_id: str | None                         # se conserva por compatibilidad
```

Índice único: `(channel, external_id)`.

Migración en tres pasos (sin ventana de corte):

1. Agregar columnas con valor por defecto; `channel='whatsapp'`,
   `external_id = wa_id` para los existentes.
2. Escribir en ambas durante una versión.
3. Pasar las consultas a `external_id` y dejar `wa_id` como alias.

### Lo que no cambia

- `conversations`, `messages`, `handoffs`, `conversation_state`: igual.
- `messages.payload` guarda el evento original del canal.
- La consola lee lo mismo; se agrega `channel` a la conversación.

## 5. Router de webhooks

```
POST /webhooks/whatsapp    (existente, HMAC)
POST /webhooks/meta        (Messenger + Instagram: misma app, distinto objeto)
POST /webhooks/meta/verify (GET de verificación de Meta)
POST /api/chat             (web chat: mensaje del visitante)
GET  /api/chat/stream      (web chat: SSE con la respuesta)
```

Todos terminan en la misma función:

```python
async def handle_inbound(inbound: Inbound) -> None:
    contacto = await contacts.get_or_create(inbound.channel, inbound.external_id)
    reply = await agent.handle(session, contacto, inbound.text, media=inbound.media)
    for mensaje in render_reply(reply, CAPACIDADES[inbound.channel]):
        await adapters[inbound.channel].send(contacto, mensaje)
```

## 6. Web chat (primer canal a implementar)

**Por qué primero**: sin aprobación de Meta, sin costo por mensaje, control
total del diseño.

- **Transporte**: `POST /api/chat` (entrada) + SSE `GET /api/chat/stream`
  (salida). Más simple que WebSocket y suficiente.
- **Sesión**: `session_id` en cookie firmada; el visitante es anónimo.
- **Identidad**: si escribe su CI, se vincula al contacto para historial de
  compras (misma lógica de privacidad que WhatsApp).
- **Widget**: script embebible (`<script src="/chat/widget.js">`) que abre un
  panel, muestra fotos y botones, y usa la misma API.
- **Consola**: el caso aparece en la bandeja igual que WhatsApp, con la
  etiqueta del canal.

## 7. Reglas por canal

| Regla | WhatsApp | Instagram | Messenger |
|---|---|---|---|
| Ventana para responder | 24 h | 24 h | 24 h |
| Mensaje iniciado por el negocio | Plantilla aprobada | Etiqueta `HUMAN_AGENT` | Etiqueta |
| Botones | 3 | 3 | 3 |
| Listas | Sí | No | No |
| Formato | `*negrita*` | plano | plano |

Consecuencia de diseño: **las respuestas del bot deben caber en las tres
primeras opciones**. Las listas largas se degradan a texto numerado.

## 8. Identidad entre canales

Un mismo cliente puede escribir por WhatsApp y por Instagram. Reglas:

- Por defecto, **contactos separados** (no se cruzan conversaciones).
- Vínculo **explícito** cuando el cliente da su CI/teléfono y lo confirma.
- Nunca se mezcla el historial sin ese paso: es un tema de privacidad.

## 9. Seguridad

| Canal | Verificación |
|---|---|
| WhatsApp | HMAC `X-Hub-Signature-256` (ya existe) |
| Messenger / Instagram | HMAC con el App Secret |
| Web chat | Cookie firmada + límite por IP + token de sesión |
| Todos | Deduplicación por `external_id` del mensaje |

## 10. Observabilidad

- `conversations.channel` visible en la bandeja.
- KPIs por canal en el panel (volumen, resolución, derivación).
- Filtro de canal en el informe del piloto.

## 11. Plan por fases

| Fase | Alcance | Esfuerzo | Criterio de aceptación |
|---|---|---|---|
| **0** | `channels/base.py` + `render.py` + tests | Hecho | Listas y botones se degradan bien |
| **1** | `contacts.channel/external_id` + migración | 1 día | WhatsApp sigue funcionando igual |
| **2** | Router único + adaptador WhatsApp sobre la capa | 1 día | 366 tests verdes |
| **3** | **Web chat** (API + SSE + widget + bandeja) | 2 días | Un visitante conversa y deriva a asesor |
| **4** | **Instagram** (webhook + adaptador) | 2–3 días | Responde DMs y deriva |
| **5** | **Messenger** (reutiliza casi todo) | 1–2 días | Responde y deriva |
| **6** | KPIs y filtros por canal | 1 día | Panel muestra el canal |

Total: **~2 semanas** después del piloto de WhatsApp.

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Instagram/Messenger exigen revisión de app | Empezar por web chat |
| Listas no existen fuera de WhatsApp | `render.py` ya las convierte |
| Respuestas largas se cortan | Límite por canal en `Capabilities` |
| Un contacto duplicado por canal | Vínculo explícito por CI |
| WhatsApp se rompe con la migración | Columna nueva aditiva + rollback |

## 13. Qué NO se hará en esta etapa

- Unificar identidad automáticamente entre canales.
- Soportar audio en todos los canales (solo transcripción cuando exista).
- Un motor de plantillas por canal (WhatsApp ya tiene el suyo).
- Cambiar el agente para “saber” el canal: la lógica comercial es la misma.
