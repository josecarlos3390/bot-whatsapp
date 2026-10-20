# Pagos con QR Simple (CUCU) en Bolivia

El scaffold trae dos proveedores:

| Proveedor | Uso | Dinero real |
|---|---|---|
| `mock_qr` | Desarrollo y demos | No |
| `cucu_qr` | Sandbox/producción de QR Simple (CUCU) | Sí, en producción |

CUCU expone una API de cobros QR con sandbox y webhooks firmados:
<https://docs.cucu.bo/payments/cobros-qr/introduccion>.

---

## 1. Flujo

```text
Cliente confirma pedido
  → backend crea Sales Order en SAP y lee DocTotal
  → POST https://qrsimple.cucu.bo/api/v1/qr
      amount, gloss, expiration, externalReference=pedido, metadata
  → CUCU devuelve qrId, qrImageUrl/base64, expiresAt
  → backend guarda Payment (provider_ref=qrId, status=pending)
  → WhatsApp envía link a /mock/pay/<payment_id> (página que muestra el QR)
  → cliente escanea y paga desde su banco
  → CUCU envía webhook qr.paid firmado
  → backend valida firma, monto y referencia
  → confirma pago, crea factura + IncomingPayment en SAP
  → notifica al cliente por WhatsApp
```

La página de pago se llama `/mock/pay/<id>` por compatibilidad, pero cuando el
proveedor es `cucu_qr` muestra el QR real de CUCU y **no** tiene botón de
confirmación manual.

---

## 2. Configuración

```env
PAYMENT_PROVIDER=cucu_qr
CUCU_API_KEY=...
CUCU_BASE_URL=https://qrsimple.cucu.bo/api/v1
CUCU_EXPIRATION=30m
CUCU_WEBHOOK_SECRET=whsec_...
```

- **API key**: se obtiene al contratar el plan de CUCU (sandbox y producción son
  llaves distintas). La documentación indica pedirla al agente de CUCU en
  WhatsApp o en `app.cucu.bo`.
- **Webhook secret**: se obtiene **una sola vez** al registrar la URL con
  `POST /api/v1/webhook`. Guárdalo en el gestor de secretos; si se pierde, se
  rota.
- **Webhook URL**: `https://<dominio>/webhooks/payments/cucu`.
- La URL debe ser HTTPS pública y resolver a una IP pública; CUCU la valida.

### Registrar el webhook

```bash
curl -X POST https://qrsimple.cucu.bo/api/v1/webhook \
  -H "X-Api-Key: $CUCU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://api.tudominio.com/webhooks/payments/cucu"}'
```

La respuesta trae `secret` (`whsec_...`). Cópialo a `CUCU_WEBHOOK_SECRET`.

### Probar el webhook

```bash
curl -X POST https://qrsimple.cucu.bo/api/v1/webhook/test \
  -H "X-Api-Key: $CUCU_API_KEY"
```

CUCU encola un evento de prueba (5 por minuto). Revisa los logs del backend.

---

## 3. Firma del webhook

CUCU usa **Standard Webhooks**:

- `webhook-id`: id de la entrega.
- `webhook-timestamp`: UNIX del envío.
- `webhook-signature`: `v1,<base64>`, puede traer varias firmas durante rotación.

El backend calcula:

```text
HMAC-SHA256(
  key = base64_decode(secret sin "whsec_"),
  message = f"{webhook-id}.{webhook-timestamp}.{raw_body}"
)
```

y compara en tiempo constante. También rechaza timestamps con más de 5 minutos
de diferencia. Un body alterado o una firma inválida devuelve `401`.

---

## 4. Idempotencia y conciliación

- `Idempotency-Key` al crear el QR: `order-<uuid del pedido>`.
- `externalReference`: número de pedido (`WA-...`).
- El backend busca el pago por `qrId` y, si no, por `externalReference`.
- `PaymentEvent.provider_event_id` guarda el `webhook-id`; un reintento devuelve
  `200` sin volver a facturar.
- El monto se compara contra `Payment.amount`; si no coincide, se rechaza.
- Si el webhook no llega, se puede consultar `GET /qr/{qrId}` y confirmar; queda
  como job de reconciliación pendiente.

---

## 5. Estados

| Estado CUCU | Estado local | Acción |
|---|---|---|
| `PENDING` | `pending` | Esperar webhook |
| `PAID` | `paid` / `invoiced` | Facturar y registrar cobro |
| `EXPIRED` | `expired` | Ofrecer regenerar QR |
| `CANCELLED` | `cancelled` | Cancelar pedido |

El scaffold implementa `PENDING → PAID → invoiced`. Los jobs de expiración y
conciliación quedan como siguiente paso.

---

## 6. Producción

- [ ] API key de producción (no la de sandbox).
- [ ] `PAYMENT_PROVIDER=cucu_qr`.
- [ ] Webhook HTTPS público registrado; secret en gestor de secretos.
- [ ] Probar un pago real de bajo monto y verificar factura + cobro en SAP.
- [ ] Conciliación diaria contra el estado de CUCU.
- [ ] Política de reembolsos y cancelaciones.
- [ ] No mostrar el botón de confirmación manual para pagos reales.

## 7. Modo mock

Para desarrollo, deja `PAYMENT_PROVIDER=mock_qr`. Genera un QR local con el
payload del pedido y una página con botón “Confirmar pago (simulado)”. Sirve para
probar todo el flujo sin mover dinero ni depender de CUCU.
