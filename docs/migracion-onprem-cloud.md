# Migrar un número On-Premises a Cloud API

## Diagnóstico del número

El ID `1403868399479683` es un **Phone Number ID**, no una WABA. Meta devuelve:

```json
{
  "display_phone_number": "+591 79462889",
  "verified_name": "Cuenta Prueba",
  "platform_type": "ON_PREMISE",
  "account_mode": "LIVE",
  "status": "DISCONNECTED",
  "code_verification_status": "NOT_VERIFIED",
  "messaging_limit_tier": "TIER_250",
  "is_pin_enabled": false
}
```

Datos de la cuenta:

- **WABA ID:** `1041492155375070` (“Cuenta Prueba”).
- **Business ID:** `4435656936748499` (“Doña Carlita”).
- **Phone Number ID:** `1403868399479683`.
- **Plantillas:** 0.
- **Verificación de negocio:** `not_verified`.
- **App suscrita:** ninguna.

Meta Support indica tres bloqueos antes de migrar:

1. Verificación del negocio.
2. Método de pago.
3. Al menos una plantilla aprobada.

---

## Bloqueos y dónde resolverlos

### 1. Verificación de negocio

Entrá a **Business Settings → Business Info**:

https://business.facebook.com/settings/business-info/?business_id=4435656936748499

O **Security Center**:

https://business.facebook.com/settings/security_center/?business_id=4435656936748499

Necesitás documentos legales que coincidan con la entidad (“Doña Carlita” o ROHO,
según corresponda), dominio, teléfono o email.

**Ojo:** la WABA pertenece a “Doña Carlita”, no a ROHO. Si ROHO es otra sociedad,
primero hay que decidir si se verifica Doña Carlita o si se transfiere/crea la
WABA correcta.

### 2. Método de pago

**WhatsApp Manager → Account Settings → Payment Methods**:

https://business.facebook.com/wa/manage/account-settings/?waba_id=1041492155375070

O **Business Settings → Billing & Payments**:

https://business.facebook.com/settings/payment-methods/?business_id=4435656936748499

Agregá tarjeta o línea de crédito. Verificá que acepte cargos internacionales.

### 3. Plantilla aprobada

**WhatsApp Manager → Message Templates**:

https://business.facebook.com/wa/manage/message-templates/?waba_id=1041492155375070

Creá una plantilla **Utility**, idioma **Spanish (es)**, por ejemplo:

```text
Nombre: pedido_confirmado_roho
Categoría: Utility
Idioma: es

Hola {{1}}, tu pedido {{2}} de ROHO fue confirmado.
Total: Bs {{3}}. Gracias por tu compra.
```

La aprobación puede tardar minutos u horas. Tiene que quedar en estado
`APPROVED`.

---

## Después de los tres bloqueos

1. Respondé al caso de soporte confirmando que ya están resueltos.
2. Pedí la migración de `platform_type=ON_PREMISE` a `CLOUD_API`.
3. Verificá el código.
4. Configurá el PIN.
5. Aprobá el nombre visible ROHO.
6. Generá token nuevo.
7. Actualizá webhook y `.env`.
8. Conectá catálogo en Commerce Manager.

La API local caducó el **23 de octubre de 2025** y ya no puede enviar ni recibir
mensajes:

https://developers.facebook.com/docs/whatsapp/on-premises/sunset/

---

## Opción A: migrar el número (conservarlo)

### 1. Entrar a WhatsApp Manager

https://business.facebook.com/wa/manage/

Números de teléfono:

https://business.facebook.com/wa/manage/phone-numbers/

Buscá **+591 79462889** y abrí su configuración.

### 2. Buscar la opción de migración

Buscá una de estas opciones:

- **Migrate to Cloud API**
- **Change hosting type**
- **Migrar a Cloud API**
- **Cambiar tipo de alojamiento**

Si aparece, seguí el asistente. El proceso puede tardar entre 5 y 60 minutos y
hay downtime.

Si **no aparece**, hay que abrir un caso con soporte de Meta (paso 4). No hay un
endpoint público documentado para hacer este cambio.

### 3. Preparar antes de migrar

- Tené a mano el **WABA ID** y el **Business ID**.
- Confirmá que el cliente On-Premises esté detenido/desconectado.
- Tené acceso al número para recibir el OTP.
- Definí el **nombre visible** (hoy es “Cuenta Prueba”; debería ser ROHO).
- Configurá el PIN de dos pasos.
- Exportá el catálogo de la app, si existe.
- Avisá a los clientes por el downtime.

### 4. Si no aparece la opción: soporte Meta

https://business.facebook.com/business/help/support/

Elegí:

- WhatsApp Business API
- Número de teléfono
- Migración / Hosting

Mensaje sugerido:

```text
Solicito migrar el número +591 79462889 (Phone Number ID 1403868399479683)
de On-Premises API a Cloud API.

WABA ID: <completar>
Business ID: <completar>
El cliente On-Premises está desconectado.
El número figura platform_type=ON_PREMISE y status=DISCONNECTED.
Necesito conservar el número y pasar a Cloud API para catálogo/carrito.
```

### 5. Después de migrar

1. Verificá que `platform_type` sea `CLOUD_API`.
2. Verificá el código (`code_verification_status=VERIFIED`).
3. Configurá el PIN (`is_pin_enabled=true`).
4. Aprobá el nombre visible ROHO.
5. Generá un token nuevo con permisos de la WABA.
6. Actualizá webhook y `.env`:

```env
WA_PHONE_NUMBER_ID=1403868399479683
WA_WABA_ID=<waba>
WA_ACCESS_TOKEN=<token nuevo>
WA_DRY_RUN=false
```

7. Conectá el catálogo en Commerce Manager y activá catálogo/carrito.

---

## Opción B: usar un número nuevo

Si la migración no avanza:

1. Conseguí un número que nunca haya estado en WhatsApp.
2. Agregalo a Cloud API desde API Setup.
3. Usá ese `Phone Number ID`.
4. Dejá el +591 79462889 como está.

Es más rápido, pero cambiás el número que ven los clientes.

---

## Qué no hacer

- No intentes agregar el número On-Premises como si fuera nuevo.
- No borres la WABA ni el número.
- No uses el mismo número en On-Premises y Cloud API.
- No reinstales WhatsApp Business en ese número.
