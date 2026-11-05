# Migrar el bot del número de prueba al número real

## Quién guía qué

| Tema | Lo lleva | Por qué |
|---|---|---|
| **Meta / WhatsApp** | **Equipo del bot** | Es la cuenta de WhatsApp Business: número, token, webhook, plantillas |
| **PaaS / VTEX** | Solo avisar | No depende del número; el carrito y el catálogo no cambian |
| **Infraestructura** (servicio, túnel, `.env`) | Equipo del bot | La configuración vive en el servidor del bot |

**Respuesta corta:** lo guía el **equipo del bot**. El PaaS solo necesita
enterarse (y confirmar que no filtra por número).

## Diferencia entre el número de prueba y el real

| | Número de prueba | Número real |
|---|---|---|
| Destinatarios | Solo **5 números** autorizados | Cualquier cliente |
| Nombre visible | Genérico | **Requiere aprobación de Meta** |
| Verificación | No | Verificación del negocio |
| Límite de mensajes | Bajo | Según calidad del número |
| Plantillas | Igual | Igual (siguen siendo obligatorias fuera de 24 h) |
| Costo | Gratis | **Se factura por conversación** |

## Antes de empezar: lo que hay que tener

| Requisito | Detalle |
|---|---|
| Número | Que **no esté en WhatsApp** (ni normal ni Business). Si tiene WhatsApp, hay que borrar la cuenta primero |
| Tipo de número | Fijo o móvil, con capacidad de recibir SMS o llamada (para el código) |
| Meta Business Manager | Cuenta verificada del negocio |
| Nombre visible | El que verán los clientes (ej. *ROHO Homecenter*) |
| Método de pago | Tarjeta para la facturación de Meta |
| Acceso de administrador | Al Business Manager y a la app de Meta |

## Pasos

### 1. Registrar el número (Meta)

1. Business Manager → **Cuentas de WhatsApp** → agregar número.
2. Elegir el número y el nombre visible.
3. Verificar por SMS o llamada.
4. Esperar la aprobación del nombre (puede tardar minutos u horas).

### 2. Obtener los datos nuevos

| Dato | Dónde |
|---|---|
| `WA_PHONE_NUMBER_ID` | WhatsApp → Configuración de la API |
| `WA_WABA_ID` | WhatsApp → Configuración de la cuenta |
| `WA_BUSINESS_NUMBER` | El número en formato internacional |
| `WA_ACCESS_TOKEN` | Token **permanente** (no el temporal de 24 h) |

### 3. Configurar el webhook

```
URL:      https://{dominio}/webhooks/whatsapp
Token:    el mismo WA_VERIFY_TOKEN del .env
Suscribir: messages
```

**Ojo:** el túnel de prueba cambia de URL al reiniciar. Para producción hace
falta un **dominio fijo**.

### 4. Actualizar el `.env` y reiniciar

```env
WA_PHONE_NUMBER_ID=...
WA_WABA_ID=...
WA_BUSINESS_NUMBER=+591...
WA_ACCESS_TOKEN=...
WA_VERIFY_TOKEN=...        # puede quedar el mismo
WA_DRY_RUN=false
```

```powershell
Restart-Service RohoBot
```

### 5. Verificar

```powershell
# Estado del número y un envío de prueba
.\.venv\Scripts\python.exe -m scripts.diagnostico_whatsapp
```

Debe devolver:

- `status` del número en `CONNECTED`
- `code_verification_status` en `VERIFIED`
- el envío de prueba llega al teléfono

### 6. Plantillas

Las plantillas aprobadas en el **número de prueba no se heredan**: hay que
volver a crearlas en la cuenta nueva.

| Plantilla | Uso |
|---|---|
| `carrito_sin_terminar` | Recordatorio de carrito |
| La de encuesta (`feedback`) | Satisfacción |

### 7. Avisar al PaaS

> Migramos el bot al número real `+591...`. No hay cambios de contrato: mismo
> carrito, mismo catálogo. Solo avisamos por si su integración filtra por
> número de WhatsApp.

## Qué se rompe si falta un paso

| Falta | Síntoma |
|---|---|
| Token permanente | El bot deja de enviar a las 24 h |
| Webhook sin `messages` | El bot recibe pero no responde |
| Nombre no aprobado | Los clientes ven un nombre genérico |
| Plantillas no recreadas | Los recordatorios fallan con `131047` |
| Dominio fijo | El túnel cambia y Meta deja de entregar |

## Durante la migración

1. **No borres el número de prueba** hasta que el real funcione.
2. Probá con tu propio número primero.
3. Revisá `logs/envios-alerta.txt`: si hay fallos seguidos, algo quedó mal.
4. Los chats existentes **no se migran**: es un número nuevo, con otra bandeja.
   Si se necesita el historial, hay que exportarlo aparte.

## Lo que no cambia

- El código del bot.
- El carrito, catálogo, precios y políticas.
- La consola y los asesores.
- La base de datos (los contactos nuevos entran con otro `wa_id`).
