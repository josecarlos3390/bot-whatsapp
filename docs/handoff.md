# Handoff a asesores

## Flujo

1. El cliente pide un asesor o el bot detecta que hace falta.
2. Se crea un `handoff` con estado `pending`.
3. La conversación queda pausada.
4. El asesor ve el caso en la bandeja.
5. Responde desde la bandeja.
6. Al resolver, el bot vuelve a atender.

## Acceso

```text
http://127.0.0.1:8000/advisor/login
```

Cada asesor tiene usuario y contraseña. La sesión se guarda en una cookie
firmada.

Crear un asesor:

```powershell
python -m scripts.create_advisor --username ana --password "..." --name "Ana"
```

La bandeja:

```text
http://127.0.0.1:8000/admin/handoffs/view
```

Si no hay sesión, redirige al login.

## Qué muestra la bandeja

- cliente y número,
- motivo,
- minutos esperando,
- SLA vencido,
- quién lo tomó,
- contexto: ciudad, tienda preferida, carrito y últimos pedidos,
- conversación,
- auditoría.

Acciones:

- **Tomar**: asigna el caso al asesor logueado.
- **Ver conversación**: últimos mensajes + contexto.
- **Responder**: envía texto por WhatsApp.
- **Resolver**: cierra y devuelve el bot a la conversación.

## Regla de atención

Mientras el handoff esté en `pending`, el composer está bloqueado.

1. El asesor pulsa **Tomar**.
2. El estado pasa a `taken`.
3. Recién ahí puede escribir o adjuntar archivos.
4. Para cerrar, pulsa **Resolver** y escribe la solución aplicada.
5. El estado pasa a `resolved` y el bot vuelve.

El backend también valida la regla: no acepta respuestas ni adjuntos si el
caso no está tomado, y exige una solución no vacía al resolver.

## Acciones adicionales

- **Transferir**: pasa el caso a otro asesor activo.
- **Devolver al bot**: cierra la atención sin marcarla como resuelta; el bot
  retoma la conversación.
- **Reabrir**: vuelve a poner el caso en atención del mismo asesor.
- **Categoría de solución**: stock, precio, pago, entrega, garantía u otro.

## Roles

| Rol | Permisos |
|---|---|
| `admin` | Todo, agentes, configuración, métricas |
| `supervisor` | Ver todos los casos, transferir, reabrir, métricas |
| `agent` | Ver y atender sus casos y los no asignados |

Los agentes no pueden administrar usuarios ni ver métricas globales.

## SLA

El SLA se pausa cuando el asesor responde y queda esperando al cliente.
Se reanuda automáticamente cuando el cliente vuelve a escribir.

## Historial y reasignación

- Pestaña **Cerrados** para ver resueltos y devueltos al bot.
- Si un caso sigue `pending` y asignado después de
  `HANDOFF_REASSIGN_MINUTES` (5 por defecto), se reasigna a otro asesor de
  guardia; si no hay otro, queda sin asignar.
- Si nadie lo toma, el bot vuelve a los 15 minutos.

## Encuesta al cliente

Al resolver se envía una lista nativa de WhatsApp:

```text
¿Cómo calificás la atención?
5 · Excelente
4 · Muy buena
3 · Regular
2 · Mala
1 · Muy mala
```

La respuesta se guarda directamente, sin pasar por el bot. También queda
disponible el link público `/survey/{token}` como respaldo.

## Métricas

En **Agentes** se muestran, para los últimos 30 días:

- casos tomados,
- resueltos,
- reabiertos,
- primera respuesta promedio,
- tiempo de resolución promedio.


## Aviso al cliente

Al tomar el caso, el cliente recibe:

```text
Tu caso fue asignado a Ana. Te va a responder por acá.
```

La bandeja se refresca cada 10 segundos.

## Administración de agentes

Un asesor con `is_admin=true` puede abrir:

```text
http://127.0.0.1:8000/admin/advisors/view
```

Ahí puede:

- crear agentes,
- activar/desactivar,
- poner o quitar guardia,
- dar o quitar permisos de administrador,
- cambiar contraseña.

La guardia se muestra en la cabecera:

```text
Guardia: Ana, Luis
```

Se pueden designar varios asesores de guardia.

## Notificaciones visibles

La bandeja:

- muestra un badge con la cantidad de handoffs abiertos,
- lanza un toast cuando aparece un caso nuevo,
- opcionalmente usa notificaciones del navegador,
- se refresca cada 10 segundos.

El botón 🔔 pide permiso al navegador. No depende de Telegram.

## SLA

```env
HANDOFF_SLA_MINUTES=5
```

Si el caso supera ese tiempo, aparece como **SLA vencido**.

## Auto-resume

```env
HANDOFF_AUTO_RESUME_MINUTES=15
```

Si nadie toma el caso en 15 minutos, el bot vuelve solo. Si el cliente escribe
`menu`, vuelve inmediatamente (solo si el caso sigue sin asignar).

## Notificación

Webhook genérico:

```env
HANDOFF_WEBHOOK_URL=https://n8n.../webhook/handoff
```

Telegram directo:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

El mensaje incluye cliente, número, motivo y link a la bandeja.

## Seguridad

- Contraseñas con PBKDF2.
- Sesión firmada con `ADVISOR_SESSION_SECRET`.
- Cookie HttpOnly.
- Cambiar `ADVISOR_SESSION_SECRET` en producción.
- Usar HTTPS y un dominio estable.
- La bandeja actual es para piloto; para producción conviene un helpdesk
  dedicado o agregar roles y permisos.
