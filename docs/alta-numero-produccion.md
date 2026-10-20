# Alta del número de producción

Checklist después de eliminar la cuenta de WhatsApp Business del número.

## 1. Confirmar que el número quedó libre

Intentá agregarlo en **Meta for Developers → tu app → WhatsApp → API Setup →
Add phone number**.

- Si te deja avanzar, quedó libre.
- Si dice que el número ya está en uso:
  - esperá unos minutos,
  - verificá que no esté en otra WABA/BSP,
  - confirmá que elegiste **Eliminar cuenta**, no solo cerrar sesión.

## 2. WABA y número

1. Entrá a **Meta Business Suite → Configuración → Cuentas → WhatsApp**.
2. Usá la WABA existente o creá una.
3. Agregá el número.
4. Recibí el OTP por SMS o llamada.
5. Definí el **nombre visible** (debe cumplir políticas).
6. Completá la verificación de negocio si falta.
7. Agregá método de pago.

## 3. Token

Generá un token de **usuario del sistema** con acceso a la WABA nueva:

- `whatsapp_business_messaging`
- `whatsapp_business_management`
- `catalog_management` (si vas a usar catálogo)

El token del número de prueba puede no tener acceso a la WABA nueva.

## 4. Webhook

1. Configurá la callback URL:
   `https://TU-DOMINIO/webhooks/whatsapp`
2. Usá el mismo `WA_VERIFY_TOKEN`.
3. Suscribí la app a la WABA:
   `POST /{WABA_ID}/subscribed_apps`
4. Verificá que lleguen los mensajes.

## 5. Catálogo y carrito

1. **Commerce Manager → Catálogo**.
2. Crear o importar productos (CSV/feed/API).
3. Conectar el catálogo a la WABA.
4. Activar:
   - `is_catalog_visible`
   - `is_cart_enabled`
5. Verificar elegibilidad del país/vertical.

Sin catálogo conectado, el número de producción no habilita catálogo nativo.

## 6. Configuración del bot

Actualizar `.env`:

```env
WA_PHONE_NUMBER_ID=<nuevo id>
WA_WABA_ID=<nueva waba>
WA_TOKEN=<token con permisos>
WA_DRY_RUN=false
```

Reiniciar API y worker. Probar:

1. Mensaje entrante.
2. Respuesta del bot.
3. “¿Qué promociones tienen?”
4. Catálogo nativo, si está habilitado.
5. Carrito nativo y webhook `order`.

## 7. Si el catálogo nativo no está disponible

El bot puede seguir usando su catálogo/carrito propio con el número de producción.
El catálogo nativo es independiente y requiere Commerce Manager; no es requisito
para vender por el bot.

## 8. “La cuenta alcanzó el límite” al agregar el número

El número de prueba **no se puede eliminar** y puede ocupar un cupo. Opciones:

1. **Liberar cupo**: WhatsApp Manager → Números de teléfono. Si hay un número
   viejo que ya no se usa, quitarlo de la WABA.
2. **Crear una WABA nueva** dedicada a producción y agregar el número ahí.
   Luego conectarla a la app.
3. **Verificar el negocio** o pedir aumento de límite a Meta si el límite es de
   la cuenta comercial.
4. Si el límite es de WABAs del portafolio, evaluar un portafolio nuevo.

No elimines la app ni el número de prueba: el número de prueba es de Meta y no
se puede borrar.
