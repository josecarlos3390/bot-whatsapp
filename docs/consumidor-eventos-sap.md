# Consumidor de eventos SAP en el bot

**Estado:** implementado. El publisher del integrador está detrás de
`Outbox:PublishEvents=false` hasta validar RabbitMQ.

## 1. Flujo

```text
SAP HANA OUTBOX_EVENTS
        ↓
Integration.Worker (.NET)
  └─ publica en `sap.events` (topic)
        ↓
Cola `chatbot.sap.events`
        ↓
`python -m app.events.consumer`
        ↓
PostgreSQL `chatbot` (`sap_event_inbox`, catálogo, compras)
```

El bot **no lee HANA**. Solo consume RabbitMQ.

## 2. Configuración

```env
SAP_EVENT_QUEUE_ENABLED=true
RABBITMQ_URL=amqp://usuario:clave@host:5672/
SAP_EVENT_EXCHANGE=sap.events
SAP_EVENT_QUEUE=chatbot.sap.events
SAP_EVENT_TENANT=tenant-001
```

En el integrador:

```json
"Outbox": {
  "PublishEvents": true,
  "EventExchange": "sap.events"
}
```

## 3. Ejecutar

Local:

```powershell
python -m app.events.consumer
```

Docker:

```powershell
docker compose --profile events up -d events
```

El servicio `events` usa `host.docker.internal:5672` para el RabbitMQ del
integrador.

## 4. Qué procesa

| `object_type` | Acción |
|---|---|
| `4` Item | Refresca `catalog_items` por `ItemCode` |
| `13` Invoice | Refresca `purchase_history` por `DocEntry` |
| `2` BusinessPartner | Ignorado por ahora |
| `17` Order | Ignorado por ahora |
| `PRICE_LIST` | Ignorado; sigue el sync programado de promociones |

Para `4` y `13` consulta el Service Layer por `AggregateId`; no confía en el
payload.

## 5. Idempotencia

Tabla `sap_event_inbox`:

- `event_id` es PK.
- Si `processed_at` existe, el evento se ignora.
- Si falla, se reintenta y se guarda `error`.
- Un evento `ignored` queda procesado con el motivo en `error`.
- RabbitMQ puede entregar duplicados; el consumidor no Duplica compras.

## 6. Reintentos y DLQ

- `x-retry` hasta 3.
- Si se agota, se rechaza y va a `chatbot.sap.events.dlq`.
- Cola principal con `x-dead-letter-exchange`.
- El consumidor usa `prefetch=10` y ack después del commit.

## 7. Limitaciones actuales

- **Contacto no vinculado:** una factura de un `CardCode` sin `Contact.sap_card_code`
  se marca `contact_not_linked`. Cuando el cliente se vincule, hay que correr
  `sync_purchases` para ese `CardCode`; no se reprocesa automáticamente.
- **Promociones:** `PRICE_LIST` no se aplica todavía; se mantiene
  `sync_promotions` cada 6 h.
- **Pedidos:** `17` todavía no actualiza estado.
- **Reconciliación:** el full sync nocturno sigue siendo necesario.
- **RabbitMQ:** 3.13 en el integrador; evaluar 4.x antes de producción.

## 8. Probar sin el integrador

Publicar un evento de prueba:

```powershell
python -m scripts.publish_test_event `
  --event-id test-item-1 `
  --object-type 4 `
  --aggregate-id DCHDCRC200193 `
  --event-type Updated
```

Si SAP no resuelve desde tu red, levantá el consumer con:

```powershell
$env:SAP_MODE="mock"
$env:SAP_LIVE_READS="false"
$env:SAP_EVENT_QUEUE_ENABLED="true"
python -m app.events.consumer
```

Así el handler `4` usa el catálogo local.

Luego revisar:

```sql
SELECT * FROM sap_event_inbox ORDER BY received_at DESC;
```

Y el catálogo:

```sql
SELECT sku, name, price, stock FROM catalog_items
WHERE sku = 'DCHDCRC200193';
```

## 9. Variables y archivos

- `app/events/consumer.py`
- `app/services/sap_events.py`
- `app/models.py` (`SapEventInbox`)
- `alembic/versions/4c767c1cac7a_sap_event_inbox.py`
- `tests/test_sap_events.py`
