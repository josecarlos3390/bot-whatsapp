# Asociar el número real a la cuenta de WhatsApp Business

Pasos para agregar el número que ya tenés a la cuenta verificada, y dejarlo
funcionando con el bot.

## Antes de empezar

- El número **no debe estar registrado** en WhatsApp Messenger ni en WhatsApp
  Business (app). Si lo está: eliminá la cuenta desde la app antes de seguir.
- Tiene que poder **recibir un SMS o una llamada** (para el código).
- Necesitás un usuario **administrador** del Business Manager.
- El nombre visible debe cumplir las reglas de Meta (sin promesas ni genéricos).

## 1. Agregar el número

1. Entrá a <https://business.facebook.com/wa/manage/phone-numbers/>.
2. Elegí la **cuenta de WhatsApp Business** verificada (arriba a la izquierda).
3. **Agregar número de teléfono**.
4. Completá:
   - Nombre visible: `ROHO Homecenter`
   - Categoría: `Shopping and retail` (o la que corresponda)
   - Descripción: opcional
5. Elegí el número y confirmá país + número.
6. Recibí el código por **SMS** o **llamada** e ingresalo.
7. Activá la **verificación en dos pasos** (código de 6 dígitos).

## 2. Copiar los identificadores

En la lista de números, al lado del nuevo, aparece el **Phone Number ID**
(un número largo, no el teléfono).

| Dato | Dónde |
|---|---|
| `WA_PHONE_NUMBER_ID` | WhatsApp Manager → Números → Phone Number ID |
| `WA_WABA_ID` | WhatsApp Manager → Configuración de la cuenta |
| `WA_BUSINESS_NUMBER` | El número con formato internacional (`+591…`) |
| `WA_ACCESS_TOKEN` | App de Meta → WhatsApp → API Setup (token permanente de usuario del sistema) |

Para un token que no vence: Business Settings → Usuarios → **Usuarios del
sistema** → generar token con permisos `whatsapp_business_messaging` y
`whatsapp_business_management`.

## 3. Actualizar el bot

Guardá una copia del `.env` actual (es el rollback) y cambiá:

```env
WA_PHONE_NUMBER_ID=<el nuevo>
WA_WABA_ID=<el de la cuenta verificada>
WA_BUSINESS_NUMBER=+591XXXXXXXX
WA_ACCESS_TOKEN=<token del sistema>
```

## 4. Re-registrar el webhook

El webhook ya está suscripto a la cuenta; si cambió la URL pública del túnel,
actualizala:

```powershell
.\.venv\Scripts\python.exe -m scripts.refresh_tunnel
```

## 5. Verificar

```powershell
.\.venv\Scripts\python.exe -m scripts.check_migration
```

Tiene que mostrar `OK` en número, cuenta, webhook y token.

Con un mensaje de prueba:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_migration --to 591XXXXXXXX
```

## 6. Reiniciar el servicio

```powershell
Restart-Service RohoBot
```

Después escribí al número desde tu celular y confirmá que el bot responde.

## Costos

Asociar el número **no empieza a cobrar**. El cobro aparece cuando enviás
mensajes facturables (plantillas de marketing/utilidad, o respuestas fuera de
la ventana de 24 h). Las respuestas a clientes que escriben primero son gratis.

Si no hay método de pago configurado, esos envíos fallan con el error
`131042`. Cargalo en <https://business.facebook.com/settings/billing>.

## Si algo sale mal (rollback)

1. Restaurá el `.env` anterior.
2. `Restart-Service RohoBot`.
3. Verificá con `scripts.check_migration`.

El número de prueba sigue existiendo en la app: se puede volver a él sin
perder nada.

## Después de migrar

- Revisar el semáforo en el panel (Operación → Preparación para producción).
- Mantener el número de prueba como entorno de ensayo.
- No activar catálogo nativo hasta tener fotos y títulos corregidos.
