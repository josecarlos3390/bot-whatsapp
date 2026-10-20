# Reutilizar `integrator-paas` como fuente de eventos

> **Estado:** consumidor del bot implementado. Publisher del integrador agregado
> detrás de `Outbox:PublishEvents=false`; activar cuando RabbitMQ esté validado.

**Fecha:** 19-oct-2026
**Proyecto revisado:** `D:\ProyectosPython\integrator-paas` (.NET 8)
**Objetivo:** que el chatbot reciba artículos, precios, promociones, facturas y
pedidos desde el outbox SAP sin duplicar el poller.

---

## 1. Lo que encontré

### 1.1 Hay dos outboxes distintos

| Outbox | Motor | Uso |
|---|---|---|
| `INTEGRATION_BUS.OUTBOX_EVENTS` | SAP HANA | Lo escribe `SBO_SP_PostTransactionNotice`; lo lee el worker .NET |
| `outbox_events` | PostgreSQL | Outbox local para publicación confiable; hoy casi no se usa |

No hay que confundirlos. El bot **no debería leer HANA directamente**.

### 1.2 Esquema real de HANA

`HanaOutboxRepository` espera:

```sql
INTEGRATION_BUS.OUTBOX_EVENTS (
    ID            NVARCHAR(36) PRIMARY KEY,
    TENANT_ID     NVARCHAR(64) NOT NULL,
    EVENT_TYPE    NVARCHAR(128) NOT NULL,  -- Created | Updated | Deleted
    OBJECT_TYPE   NVARCHAR(30),            -- 2, 4, 13, 17...
    AGGREGATE_ID  NVARCHAR(128) NOT NULL,  -- CardCode, ItemCode, DocEntry
    PAYLOAD       NCLOB,
    OCCURRED_AT   TIMESTAMP NOT NULL,
    PROCESSED_AT  TIMESTAMP,
    ATTEMPT_COUNT INTEGER NOT NULL,
    ERROR_MESSAGE NVARCHAR(4000),
    IS_DEAD_LETTER TINYINT NOT NULL,
    LEASED_UNTIL  TIMESTAMP
)
```

`sql/hana_schema.sql` está desactualizado: no incluye `OBJECT_TYPE`, `PAYLOAD`
ni `LEASED_UNTIL`. Los scripts `hana-post-transaction-notice-v2.sql`,
`hana-add-payload-column.sql` y `hana-add-leased-until-column.sql` los agregan.

### 1.3 Cómo procesa hoy

- `OutboxDispatcherWorker` corre cada 5 s.
- `HanaOutboxDispatcher` lee lote, adquiere lease, procesa y marca
  `PROCESSED_AT` en HANA.
- El switch solo cubre:
  - `2` BusinessPartners
  - `13` Invoices
  - `PRICE_LIST` / `PRICE_LIST_HEADER` (polling de precios)
- `17` Orders aparece en prioridades, pero no en el switch.
- **Implementado:** publica a `sap.events` si `Outbox:PublishEvents=true`
  (`ISapEventPublisher`), con fan-out para el bot.
- El bot consume `chatbot.sap.events`; ver `consumidor-eventos-sap.md`.

### 1.4 Riesgos de seguridad

Hay credenciales reales en `appsettings.json`, `.env` y `docker-compose.yml`
(SAP, HANA, PostgreSQL, Hansa). **No las repito acá.** Si el repo se compartió o
commiteó, hay que rotarlas y moverlas a variables/secrets.

También el usuario HANA es `SYSTEM`; para producción conviene un usuario
least-privilege con `SELECT` sobre `INTEGRATION_BUS.OUTBOX_EVENTS`.

---

## 2. Arquitectura recomendada

No conectar el bot a HANA. Reutilizar el integrador como **gateway de eventos**:

```text
SAP B1
  └─ SBO_SP_PostTransactionNotice
        ↓
INTEGRATION_BUS.OUTBOX_EVENTS (HANA)
        ↓
Integration.Worker (.NET)
  ├─ procesa CRM (actual)
  └─ publica en RabbitMQ exchange `sap.events`
        ↓
Cola `chatbot.sap.events` (+ DLQ)
        ↓
Bot Python (nuevo consumidor)
        ↓
PostgreSQL `chatbot` (catálogo, promos, compras)
```

Ventajas:

- Se reutiliza el poller, lease, prioridad, reintentos e idempotencia del
  integrador.
- El bot no necesita driver HANA ni credenciales HANA.
- El evento se entrega a CRM y al bot sin competir por `PROCESSED_AT`.
- Si el bot está caído, la cola conserva los eventos.

### Alternativa simple (MVP)

El integrador escribe una copia en una tabla PostgreSQL `sap_event_feed` y el bot
la lee por `id`/`occurred_at`.

- Menos infraestructura.
- Menos acoplamiento que leer HANA.
- Pero el bot depende de la base del integrador y hay que limpiar la tabla.

Para producción, RabbitMQ es mejor porque ya está en el stack.

---

## 3. Contrato de evento

Envelope sugerido:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "RETAIL_QA5",
  "event_type": "Created",
  "object_type": "13",
  "aggregate_id": "260191954",
  "occurred_at": "2026-10-19T20:00:00Z",
  "payload": null
}
```

- Routing key: `{object_type}.{event_type}` → `13.Created`.
- Exchange: `sap.events` (topic, durable).
- Queue bot: `chatbot.sap.events` (durable, DLQ).
- Mensajes persistentes y publisher confirms.

### Mapeo al bot

| object_type | Entidad SAP | aggregate_id | Acción |
|---|---|---|---|
| `2` | BusinessPartner | CardCode | Actualizar perfil/`sap_card_code` |
| `4` | Item | ItemCode | Refrescar catálogo y precios |
| `13` | Invoice | DocEntry | Refrescar historial de compras |
| `17` | Order | DocEntry | Estado del pedido |
| `15` | Delivery | DocEntry | Estado de entrega (opcional) |
| `14` | CreditMemo | DocEntry | Devolución (opcional) |
| `22` | PurchaseOrder | DocEntry | No aplica a B2C |
| `PRICE_LIST` | Polling ITM1 | payload | Precios/promociones |
| `PRICE_LIST_HEADER` | Polling OPLN | payload | Cabecera de lista |

Para `4` y `13`, el bot consulta el Service Layer por `AggregateId`; no confía
en un payload viejo. Para `PRICE_LIST`, usa el `PAYLOAD` del evento.

---

## 4. Cambios necesarios en el integrador

1. Crear `ISapEventPublisher` y publicar en `sap.events`.
2. Llamarlo al inicio de `ProcessEventAsync`, antes de CRM:
   - si publica OK, el bot recibe el evento;
   - si CRM falla, el evento se reintenta y el bot debe ser idempotente.
3. Si la publicación falla, no marcar `PROCESSED_AT`; reintentar.
4. Publicar también `PRICE_LIST`/`PRICE_LIST_HEADER`.
5. Agregar `17` Orders al switch si el bot necesita estado de pedidos.
6. Tests de publicación, routing key y fallback.

No modificar el significado de `PROCESSED_AT`: sigue siendo “CRM procesado”.
El bot tiene su propia idempotencia por `event_id`.

---

## 5. Cambios en el bot

1. Consumidor RabbitMQ (`aio-pika`) de `chatbot.sap.events`.
2. Tabla `sap_event_inbox`:
   ```sql
   event_id UUID PRIMARY KEY,
   tenant_id TEXT,
   object_type TEXT,
   event_type TEXT,
   aggregate_id TEXT,
   occurred_at TIMESTAMPTZ,
   processed_at TIMESTAMPTZ,
   attempts INT,
   error TEXT
   ```
3. Handler por `object_type`.
4. Upsert idempotente; ignorar duplicados.
5. Reintentos con backoff; DLQ.
6. Full sync nocturno como reconciliación.

---

## 6. PostgreSQL, Docker y versiones

### Reutilizar PostgreSQL

Sí, pero **base separada**:

- Integrador: `integration_bus` (EF Core).
- Bot: `chatbot` (Alembic).

Mismo servidor, distinto database y usuario. No compartir tablas ni historial de
migraciones.

```env
DATABASE_URL=postgresql+asyncpg://chatbot_app:...@postgres:5432/chatbot
```

En Docker, el host es `postgres` y el puerto interno `5432`; desde el host es
`localhost:5434`.

### Versiones

| Componente | Hoy | Recomendación |
|---|---|---|
| PostgreSQL | 16-alpine | 16 está soportado; no es urgente. Para instalación nueva, 17/18 |
| RabbitMQ | 3.13-management-alpine | 3.13 está viejo; evaluar 4.1/4.2 con MassTransit |
| Redis | No existe en el integrador | Agregar 7.4/8 para Arq/caché del bot |
| .NET | 8 | Soporte termina nov-2026; planificar .NET 10 |
| Seq | 2024 | OK |

No actualizar PostgreSQL solo por moda: si ya hay datos, un `pg_upgrade` o
dump/restore tiene riesgo. RabbitMQ 3.13 es más urgente si se va a usar como bus
del bot.

### Docker

- `postgres:5434`, `rabbitmq:5672/15672`, `seq:5341/8080`.
- API/Worker no están en compose por HANA ODBC.
- Si el bot corre en Docker, usar una red compartida y nombres de servicio.
- El bot necesita Redis; el integrador no lo tiene.

---

## 7. Plan de implementación

### Fase 1 — Contrato y publicación

- Definir envelope y routing keys.
- Agregar publisher al integrador.
- Probar con un evento de factura y un log de RabbitMQ.

### Fase 2 — Consumidor bot

- Consumidor `aio-pika`.
- `sap_event_inbox`.
- Handler `13` → historial; `4` → catálogo/precio.
- Idempotencia y DLQ.

### Fase 3 — Promociones y pedidos

- `PRICE_LIST` → promociones.
- `17` → estado de pedido.
- Reconciliación nocturna.

### Fase 4 — Infra

- Base `chatbot` en PostgreSQL.
- Redis para Arq.
- Upgrade RabbitMQ controlado.
- Rotar credenciales y sacar secrets del repo.

---

## 8. Decisión sugerida

1. **No** leer HANA directamente desde Python.
2. **Sí** reutilizar el integrador y publicar a RabbitMQ.
3. **Sí** reutilizar el servidor PostgreSQL, con base `chatbot` separada.
4. **No** actualizar PostgreSQL 16 ahora; sí planificar RabbitMQ 4.x y Redis.
5. **Primero** el contrato de eventos y el publisher; después el consumidor.
