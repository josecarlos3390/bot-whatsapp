# Configuración de WhatsApp Cloud API (Meta)

Guía práctica para dejar el canal listo. Los nombres de menú de Meta cambian con
frecuencia; si no encuentras una opción, búscala por su nombre en Business Suite o
en la documentación oficial.

---

## 0. Antes de empezar

Necesitas:

- **Portfolio de negocio** en [business.facebook.com](https://business.facebook.com)
  con los datos legales de la empresa.
- **Documentos** para verificación: identificación fiscal (NIT), documento legal,
  web/dominio y, si aplica, factura de servicios.
- **Número de teléfono** dedicado, con capacidad de recibir SMS o llamada.
- **Método de pago** para la WABA.
- **Un dominio con HTTPS** para el webhook (Cloudflare Tunnel, ngrok o hosting).
- **Política de privacidad** pública y datos de contacto.

> El número **no debe estar registrado** en WhatsApp Consumer ni en la app WhatsApp
> Business. Si ya lo está, hay que eliminarlo/migrarlo o evaluar la coexistencia.
> Para el +591 79462889 verifica primero en qué estado está.

---

## 1. Mapa de identificadores

| Dato | Dónde se obtiene | Variable |
|---|---|---|
| App ID | App de Meta > Configuración > Básica | — |
| App Secret | App > Configuración > Básica | `WA_APP_SECRET` |
| WABA ID | WhatsApp Manager / app > WhatsApp > Configuración de la API | — |
| Phone Number ID | App > WhatsApp > Configuración de la API | `WA_PHONE_NUMBER_ID` |
| Token permanente | Usuario del sistema | `WA_ACCESS_TOKEN` |
| Verify Token | Lo inventas tú | `WA_VERIFY_TOKEN` |
| Número visible | WhatsApp Manager | `WA_BUSINESS_NUMBER` |

---

## 2. Portfolio y verificación de negocio

1. Entra a **Business Settings** y completa el perfil: nombre legal, dirección,
   teléfono, web y correo.
2. Abre **Security Center** (o “Centro de seguridad”) y solicita la
   **verificación de negocio**.
3. Sube los documentos. Meta puede pedir una video-verificación o una factura de
   servicios.
4. Espera la aprobación. Sin verificación, los límites de mensajería y varias
   funciones quedan restringidos.

Esto puede tardar de horas a varios días. **Es la ruta crítica del proyecto.**

---

## 3. Crear la WABA

1. En **WhatsApp Manager** elige “Crear cuenta de WhatsApp Business”.
2. Selecciona el portfolio de negocio.
3. Completa nombre visible, zona horaria y categoría.
4. Acepta las políticas de comercio y de mensajería.

La WABA es el contenedor de números, plantillas, calidad y facturación.

---

## 4. Crear la app y vincular WhatsApp

1. Entra a [developers.facebook.com](https://developers.facebook.com) y crea una
   app de tipo **Business**.
2. Agrega el producto **WhatsApp**.
3. Vincula la WABA creada.
4. En **WhatsApp > Configuración de la API** verás el número de prueba, el
   `Phone Number ID` y un token temporal.
5. El **número de prueba** sirve para desarrollo: permite hasta 5 destinatarios
   que debes agregar manualmente.

No uses el token temporal en producción: expira en 24 horas.

---

## 5. Número de producción

1. En **WhatsApp Manager > Números de teléfono**, agrega el número.
2. Verifica por SMS o llamada.
3. Registra el número con un **PIN de 6 dígitos** (verificación en dos pasos).
   Guárdalo en el gestor de secretos.
4. Revisa el **display name**: debe corresponder al negocio y cumplir las políticas.
5. Espera la aprobación del nombre.

Si el número ya está en WhatsApp:
- **Migración:** eliminar la cuenta de WhatsApp/WhatsApp Business y registrar el
  número en la Cloud API.
- **Coexistencia:** Meta permite usar el mismo número en la app Business y en la
  API, con limitaciones. Confirma que tu proveedor y tu caso la soportan.

---

## 6. Token permanente (usuario del sistema)

1. En **Business Settings > Usuarios > Usuarios del sistema**, crea uno
   (por ejemplo `chatbot-integracion`) con rol de administrador.
2. Asígnalo al portfolio y a la WABA.
3. Genera un token con permisos:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
   - `business_management`
4. Elige duración **permanente** si la interfaz lo permite.
5. Guárdalo en `.env` o en un secret manager. **Nunca** en Git.

Si el token se filtra, revócalo y genera otro.

---

## 7. Webhook

### 7.1 URL pública

El webhook debe ser HTTPS con certificado válido (no autofirmado) y responder
`200` en pocos segundos. Para desarrollo:

```powershell
cloudflared tunnel --url http://localhost:8000
```

o

```powershell
ngrok http 8000
```

Copia la URL pública y configura `PUBLIC_BASE_URL` con ella (el link de pago se
abre desde el teléfono del cliente).

### 7.2 Configurar en Meta

1. App > **WhatsApp > Configuración**.
2. En **Webhook**, edita:
   - Callback URL: `https://<dominio>/webhooks/whatsapp`
   - Verify token: el mismo valor de `WA_VERIFY_TOKEN`.
3. Haz clic en **Verificar y guardar**. Meta hará un `GET` con
   `hub.mode=subscribe`, `hub.verify_token` y `hub.challenge`; el backend responde
   el challenge.
4. Suscribe el campo **`messages`**. Opcional:
   `message_template_status_update`, `account_update`,
   `phone_number_quality_update`.

### 7.3 Probar la verificación a mano

```powershell
curl.exe "https://<dominio>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=TU_TOKEN&hub.challenge=12345"
```

Debe devolver `12345` en texto plano.

### 7.4 Firma de los webhooks

Cada `POST` trae `X-Hub-Signature-256`, calculado con el **App Secret**. El
backend lo valida con HMAC SHA-256; si no coincide, responde `403`. Configura
`WA_APP_SECRET` y no lo compartas.

---

## 8. App Review y modo Live

Para producción:

1. Completa la **política de privacidad** y la URL de eliminación de datos.
2. Solicita **acceso avanzado** a `whatsapp_business_messaging` y
   `whatsapp_business_management` si vas a operar fuera de tu propia WABA.
3. Envía la app a revisión con un video o instrucciones de uso.
4. Pasa la app a **Live**.

Si sólo operas tu propia WABA con un usuario del sistema, puede que no necesites
acceso avanzado al inicio, pero la verificación de negocio y el modo Live sí son
necesarios para escalar.

---

## 9. Plantillas

1. **WhatsApp Manager > Plantillas de mensajes > Crear plantilla**.
2. Elige categoría:
   - **Utility**: confirmación de pedido, pago, envío, cancelación.
   - **Marketing**: promociones y recuperación de carrito.
   - **Authentication**: OTP (no aplica a este bot).
3. Idioma: `es` (y los que uses).
4. Variables `{{1}}`, `{{2}}` con ejemplos válidos.
5. Botones permitidos: respuesta rápida, URL, teléfono.
6. Espera la aprobación (minutos u horas). Si la rechazan, corrige y apela.

Plantillas mínimas sugeridas:

| Plantilla | Categoría | Variables |
|---|---|---|
| `pedido_confirmado` | Utility | nombre, número, total |
| `pago_link` | Utility | número, total, url |
| `pago_confirmado` | Utility | número, factura |
| `pedido_enviado` | Utility | número, guía |
| `carrito_abandonado` | Marketing | nombre, producto |

Fuera de la ventana de 24 h sólo se puede iniciar con plantilla aprobada.

---

## 10. Catálogo y Flows (opcional)

- **Catálogo:** Commerce Manager > Catálogo > conectar a la WABA. Requiere feed
  (CSV/XML/API), moneda, envíos y cumplimiento de políticas.
- **Flows:** WhatsApp Manager > Flujos > crear/publicar. Necesita un endpoint de
  *data exchange* HTTPS con cifrado. Es la vía para un carrito propio dentro del
  chat.

El scaffold usa texto + botones + link de pago; Flows es la fase siguiente.

---

## 11. Prueba end-to-end

1. `WA_DRY_RUN=false` y `WA_ACCESS_TOKEN` configurado.
2. Agrega tu número a la lista de destinatarios del número de prueba.
3. Envía `hola` al número de prueba.
4. Revisa logs del webhook y la respuesta.
5. Prueba un botón, un link CTA y una plantilla.
6. Verifica que el link de pago abra desde el teléfono (no `localhost`).

Para depurar webhooks, Meta muestra las entregas y reintentos en la app.

---

## 12. Errores comunes

| Código / error | Causa probable |
|---|---|
| `401` / `190` | Token vencido, revocado o sin permisos. |
| `131030` | El destinatario no está en la lista del número de prueba. |
| `131047` | Fuera de la ventana de 24 h: usa plantilla. |
| `132000` | Cantidad o formato de variables de plantilla incorrecto. |
| `132001` | La plantilla no existe o no está aprobada en ese idioma. |
| `131026` | Mensaje no entregable (número inválido o sin WhatsApp). |
| `100` | Parámetro inválido (teléfono, tipo de mensaje, botón). |
| Webhook no verifica | URL no pública, TLS inválido, token distinto o respuesta no es texto plano. |
| Webhook duplicado | Meta reintenta; el backend debe deduplicar por `message.id`. |

---

## 13. Checklist de producción

- [ ] Verificación de negocio aprobada.
- [ ] Número registrado y display name aprobado.
- [ ] PIN de dos pasos guardado.
- [ ] Token permanente en secret manager.
- [ ] `WA_APP_SECRET` configurado y firma validada.
- [ ] Webhook público con TLS y `messages` suscrito.
- [ ] App en Live y permisos necesarios.
- [ ] Plantillas utility aprobadas.
- [ ] Método de pago de la WABA cargado.
- [ ] Límite de mensajería y quality rating monitoreados.
- [ ] Opt-in documentado y opción de baja.
- [ ] `PUBLIC_BASE_URL` con dominio público HTTPS.
- [ ] Cola habilitada (`QUEUE_ENABLED=true`) para responder rápido al webhook.

---

## 14. Costos

Meta cobra por mensaje de plantilla y, desde el 1-oct-2026, también por los
mensajes de servicio (respuestas del bot/humano dentro de la ventana de 24 h).
Los mensajes entrantes siguen gratis. Consulta el rate card de Bolivia en tu
WhatsApp Manager antes de presupuestar; no uses tarifas de otros países.

Diseña respuestas consolidadas: cada mensaje de negocio cuenta.
