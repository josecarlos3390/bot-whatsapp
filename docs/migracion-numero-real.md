# Migración del número de prueba al número real

## Quién hace qué

| Tema | Equipo |
|---|---|
| Cuenta de WhatsApp Business, número, token, webhook, plantillas | **Bot** |
| Dominio fijo (DNS) | Infraestructura / Bot |
| Carrito, catálogo, checkout | **PaaS** (solo se avisa) |

**En corto:** lo guía el equipo del bot. El PaaS solo recibe un aviso.

## Antes de empezar: 3 definiciones

| # | Definición | Ejemplo |
|---|---|---|
| 1 | **Número** (fijo o móvil boliviano) | `+591 3xxxxxxx` |
| 2 | **Nombre visible** que verá el cliente | `ROHO Homecenter` |
| 3 | **Dominio fijo** para el webhook | `bot.roho.com.bo` |

⚠️ El número **no debe tener WhatsApp activo**. Si lo tiene, hay que borrar esa
cuenta primero (WhatsApp normal o Business).

⚠️ El túnel actual (`*.trycloudflare.com`) **cambia al reiniciar**. Con un
dominio fijo eso deja de ser un problema.

---

## Parte 1 · En Meta (lo hacemos acá)

### 1.1 Agregar el número

[WhatsApp Manager → Números de teléfono](https://business.facebook.com/wa/manage/phone-numbers/)
→ **Agregar número de teléfono**

- Nombre visible: el definido
- Categoría: Retail / Comercio
- Descripción: “Productos para el hogar”
- Verificación: SMS o llamada

### 1.2 Aprobar el nombre

Meta revisa el nombre visible. Puede tardar minutos u horas.
[Guía oficial](https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers)

### 1.3 Método de pago

[Configuración del negocio → Facturación](https://business.facebook.com/settings/)
Sin método de pago, el número queda limitado.

### 1.4 Obtener los datos del número

[App de Meta → WhatsApp → Configuración de la API](https://developers.facebook.com/apps/)

| Dato | Dónde |
|---|---|
| `WA_PHONE_NUMBER_ID` | “Identificador del número de teléfono” |
| `WA_WABA_ID` | “Identificador de la cuenta de WhatsApp Business” |
| `WA_BUSINESS_NUMBER` | El número en formato `+591…` |

### 1.5 Token permanente

[Configuración del negocio → Usuarios del sistema](https://business.facebook.com/settings/system-users)

1. Crear un usuario del sistema (o usar uno existente).
2. **Generar token** con estos permisos:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
3. Copiarlo. **Es el `WA_ACCESS_TOKEN`.**
   [Guía de tokens](https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens)

⚠️ El token de “Configuración de la API” dura **24 horas**. Para producción
hace falta el del usuario del sistema.

### 1.6 Webhook

[App → WhatsApp → Configuración](https://developers.facebook.com/apps/)

| Campo | Valor |
|---|---|
| URL de devolución | `https://{dominio}/webhooks/whatsapp` |
| Token de verificación | el `WA_VERIFY_TOKEN` del `.env` |
| Campos suscritos | **`messages`** |

### 1.7 Plantillas

[WhatsApp Manager → Plantillas de mensajes](https://business.facebook.com/wa/manage/message-templates/)

Las del número de prueba **no se heredan**. Hay que recrear:

| Plantilla | Texto |
|---|---|
| `carrito_sin_terminar` | ver `docs/plantilla-carrito-abandonado.md` |
| Encuesta de satisfacción | la que ya usa el bot |

---

## Parte 2 · En el servidor (lo hacemos acá)

### 2.1 Dominio fijo

Opciones, de mejor a peor:

| Opción | Ventaja |
|---|---|
| Subdominio del dominio propio (`bot.roho.com.bo`) | Estable, HTTPS, sin costo |
| Túnel nombrado de Cloudflare | Estable, requiere cuenta |
| Túnel rápido (hoy) | Cambia en cada reinicio ❌ |

### 2.2 Actualizar `.env`

```env
WA_PHONE_NUMBER_ID=...
WA_WABA_ID=...
WA_BUSINESS_NUMBER=+591...
WA_ACCESS_TOKEN=...
WA_VERIFY_TOKEN=...        # puede quedar el mismo
WA_DRY_RUN=false
PUBLIC_BASE_URL=https://{dominio}
```

### 2.3 Reiniciar y verificar

```powershell
Restart-Service RohoBot
.\.venv\Scripts\python.exe -m scripts.diagnostico_whatsapp
```

Debe mostrar:

- `status` del número en **CONNECTED**
- `code_verification_status` en **VERIFIED**
- el mensaje de prueba llega al teléfono

### 2.4 Probar de punta a punta

1. Escribir al número nuevo desde tu celular.
2. Pedir un producto, agregarlo al carrito y cerrar el pedido.
3. Verificar el link de VTEX.
4. Revisar que el caso llegue a la consola.

### 2.5 Vigilar

```powershell
Get-Content logs\envios-alerta.txt -Tail 5
```

Si dice “el bot lleva 3 envíos fallidos seguidos”, el token o el número están
mal.

---

## Parte 3 · Aviso al PaaS

Mensaje corto, sin pedir cambios:

> Migramos el bot al número real `+591…` (`phone_number_id …`).
> No hay cambios de contrato: mismo carrito, mismo catálogo, mismo checkout.
> Solo avisamos por si su integración filtra por número de WhatsApp.

**Lo único que podría necesitar el PaaS:** confirmar que no filtra por
`wa_id` ni por `phone_number_id`.

---

## Qué se rompe si falta un paso

| Falta | Síntoma |
|---|---|
| Token permanente | Deja de enviar a las 24 h (`131047`/401) |
| Webhook sin `messages` | Recibe pero no responde |
| Nombre sin aprobar | Los clientes ven un nombre genérico |
| Plantillas no recreadas | Los recordatorios fallan |
| Dominio fijo | Tras un reinicio Meta deja de entregar |
| Método de pago | Límite de conversaciones |

## Checklist

```
Antes
[ ] Número definido y sin WhatsApp activo
[ ] Nombre visible definido
[ ] Dominio fijo definido

Meta
[ ] Número agregado y verificado
[ ] Nombre aprobado
[ ] Método de pago cargado
[ ] Phone number ID y WABA ID anotados
[ ] Token permanente generado
[ ] Webhook con URL, token y campo messages
[ ] Plantillas recreadas

Servidor
[ ] .env actualizado
[ ] Servicio reiniciado
[ ] diagnostico_whatsapp en verde
[ ] Prueba real desde un celular
[ ] logs/envios-alerta.txt sin errores

Cierre
[ ] PaaS avisado
[ ] Testers avisados del número nuevo
[ ] Número de prueba conservado una semana
```

## Número asignado

**+591 69114625** (nombre visible: *ROHO Homecenter*).

Estado al 6/11/2026: nombre **en revisión** y número **pendiente**. No se puede
usar hasta que pase a **CONNECTED**.

Mientras espera:

| Tarea | Quién | ¿Se puede ahora? |
|---|---|---|
| Dominio fijo para el webhook | Bot / sistemas | ✅ |
| Método de pago | Negocio | ✅ |
| Token permanente | Bot | ✅ |
| Plantillas recreadas | Bot | ✅ |
| Cambiar el .env | Bot | ⏸ espera el phone_number_id y el estado CONNECTED |

### Verificar el estado

`powershell
# El número del .env
.\.venv\Scripts\python.exe -m scripts.verificar_numero

# Uno puntual (por ejemplo el nuevo)
.\.venv\Scripts\python.exe -m scripts.verificar_numero --id 123456789
`

El script falla (exit 1) si el número todavía no sirve y dice qué falta.

### El otro número

+591 72104406 (ROHO Homecenter entregas) está conectado y con calidad alta,
pero su nombre visible fue **rechazado**. No se usa para el bot salvo que se
decida lo contrario; si se usa, primero hay que corregir el nombre y darlo de
baja de la app de WhatsApp del teléfono.

## Estado real de la migración (6/11/2026)

| Paso | Estado |
|---|---|
| Número dado de alta | ✅ `+591 69114625` |
| Verificación por SMS | ✅ `VERIFIED` |
| **Registro en la API** (PIN) | ✅ `CONNECTED` |
| Nombre visible | ✅ ROHO Homecenter |
| Token permanente | ✅ usuario del sistema `bot-whatsapp` |
| Token guardado en `.env` | ✅ |
| `WA_PHONE_NUMBER_ID` | ✅ `1448102138378768` |
| `WA_WABA_ID` | ✅ `106975815570848` |
| Cuenta suscrita a la app | ✅ `subscribed_apps` |
| Servicio reiniciado | ⏳ |
| Prueba desde un celular | ⏳ |

### Números de la misma cuenta

| Número | Nombre | Estado |
|---|---|---|
| `+591 69114625` | ROHO Homecenter | CONNECTED (el del bot) |
| `+591 72100717` | ROHO Homecenter | CONNECTED |
| `+591 67706000` | MAESTRO Constructor | CONNECTED |
| `+591 72104406` | ROHO Homecenter entregas | nombre rechazado |

### Cómo se registró

```bash
POST /1448102138378768/register
{"messaging_product": "whatsapp", "pin": "<6 dígitos>"}
```

El PIN queda como verificación en dos pasos del número: hay que guardarlo.
Sin él no se puede volver a registrar el número.

### Pendiente crítico

El webhook de la app apunta al túnel de Cloudflare, que **cambia de URL al
reiniciar**. Para producción hace falta un dominio fijo.

