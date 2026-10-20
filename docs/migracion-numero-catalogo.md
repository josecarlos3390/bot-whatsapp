# Cambiar el número y habilitar catálogo/carrito

## 1. ¿Hay que desinstalar WhatsApp Business?

Depende de dónde esté el número:

| Situación | Qué hacer |
|---|---|
| El número está en la **app WhatsApp Business** y querés usarlo en Cloud API | **Eliminar la cuenta** de WhatsApp Business, no solo desinstalar |
| Querés conservar el número en la app | Usar un **número nuevo** para Cloud API |
| El número ya está en **otra WABA/API** | **Migrar** el número entre WABAs, no eliminarlo |
| El número está en un **BSP** | Pedir la migración al BSP y luego onboard en Cloud API |

**Desinstalar la app no libera el número.** Sigue registrado en WhatsApp. Para
usarlo en Cloud API hay que eliminar la cuenta desde la app:

> WhatsApp Business → Ajustes → Cuenta → Eliminar cuenta

Antes:

- Hacé backup de chats (no se migra a Cloud API).
- Tené a mano el PIN de verificación en dos pasos.
- Exportá el catálogo de la app si lo usás; el catálogo de la app no se migra
  automáticamente a Commerce Manager.

Después de eliminar la cuenta, el número queda libre para registrarlo en la
plataforma de WhatsApp Business (Cloud API).

---

## 2. Catálogo y carrito nativos

No alcanza con un número de producción. Necesitás:

1. **WABA** (WhatsApp Business Account) y número de producción.
2. **Business Manager** con verificación de negocio.
3. **Commerce Manager** con catálogo de productos aprobado.
4. Catálogo **conectado a la WABA**.
5. `is_catalog_visible` y `is_cart_enabled` activos.
6. País/vertical elegible para catálogo y carrito.

El número de prueba **no** puede usar catálogo/carrito nativos.

Para verificar el estado:

```http
GET /{PHONE_NUMBER_ID}/whatsapp_commerce_settings
    ?fields=is_catalog_visible,is_cart_enabled
```

Referencias:

- [Phone numbers](https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers)
- [Catálogos](https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/)
- [Catalog messages](https://developers.facebook.com/documentation/business-messaging/whatsapp/catalogs/catalog-messages/)

---

## 3. Diferencia importante

| Catálogo/carrito del bot | Catálogo/carrito nativo de WhatsApp |
|---|---|
| Vive en la base del bot | Vive en Commerce Manager/Meta |
| Funciona con número de prueba y destinatarios permitidos | Requiere número de producción y catálogo aprobado |
| El bot arma el carrito y el QR | El cliente arma el carrito dentro de WhatsApp |
| No necesita sincronizar productos a Meta | Hay que alimentar el catálogo de Meta |
| Ya está implementado | Hay que implementarlo |

Si querés el **catálogo nativo**, el catálogo de SAP no se conecta solo: hay que
sincronizar productos a Commerce Manager (feed/API) y manejar los mensajes de
pedido (`order`) que llegan por WhatsApp.

---

## 4. Pasos recomendados

### Opción A: mismo número

1. Backup y exportar catálogo de la app.
2. Eliminar la cuenta de WhatsApp Business en la app.
3. Crear/completar WABA en Meta Business.
4. Registrar el número en Cloud API y recibir OTP.
5. Verificación de negocio, nombre visible y método de pago.
6. Crear catálogo en Commerce Manager, importar productos y conectarlo a la WABA.
7. Activar catálogo/carrito.
8. Actualizar `.env`:
   - `WA_PHONE_NUMBER_ID`
   - `WA_TOKEN`
   - `WA_WABA_ID`
9. Actualizar webhook y probar.

### Opción B: número nuevo

1. Registrar el número nuevo en Cloud API.
2. Dejar el número actual en WhatsApp Business si lo necesitás para atención.
3. Conectar catálogo/carrito al número nuevo.
4. Comunicar el cambio a los clientes.

Es la opción con menos downtime, pero cambiás el número que ven los clientes.

---

## 6. Caso especial: número en On-Premises API

Si el número ya está registrado en WhatsApp Business API **On-Premises**, no se
puede agregar directo a Cloud API. Hay que migrarlo:

1. Confirmar la WABA/negocio dueño y el proveedor on-premise.
2. Desconectar el cliente on-premise.
3. Iniciar la migración a Cloud API desde Meta.
4. Verificar el código y configurar el PIN.
5. Aprobar el nombre visible y conectar catálogo.

Señales en Graph API:

```json
{
  "display_phone_number": "+591 79462889",
  "platform_type": "ON_PREMISE",
  "account_mode": "LIVE",
  "status": "DISCONNECTED",
  "code_verification_status": "NOT_VERIFIED"
}
```

`platform_type=ON_PREMISE` confirma que no es Cloud API. Si no tenés acceso al
proveedor on-premise, usá un número nuevo para Cloud API.

---

## 7. Antes de migrar

- Confirmar que el país y la cuenta son elegibles para catálogo/carrito.
- Tener productos con imágenes, precios, moneda y disponibilidad.
- Definir quién administra Commerce Manager.
- Probar en un número de prueba de API antes de migrar el principal.
- No usar el mismo número en app y API al mismo tiempo.
