# Actualización periódica y eventos SAP

> **Estado:** PENDIENTE (ver [pendientes.md](pendientes.md)). Hoy el bot usa cron
> + full sync; esta es la arquitectura objetivo.

**Pregunta:** ¿el bot ya se actualiza solo? ¿Conviene usar “post transaction” y
una tabla de eventos?

## 1. Lo que hace hoy

El bot **sí tiene actualización programada**, pero es por cron + full sync, no
por eventos:

| Dato | Frecuencia | Mecanismo |
|---|---|---|
| Catálogo | 03:20 | `scripts/sync_catalog.py` full |
| Promociones | cada 6 h | `scripts/sync_promotions.py` full |
| Compras | 04:10 | `scripts/sync_purchases.py` por `CardCode` |
| Precio/stock de un SKU | al consultar | SAP en vivo, caché 60 s |
| Stock por tienda | al consultar | SAP en vivo |

Requiere `QUEUE_ENABLED=true` y el worker Arq corriendo. Si no, se ejecuta a mano.

**Limitaciones:**

- Una promo nueva puede tardar hasta 6 h en aparecer.
- Una factura nueva no aparece en el historial hasta el día siguiente.
- El catálogo completo se reemplaza todas las noches.
- No hay evento instantáneo de SAP.

---

## 2. ¿Sirve el “post transaction”?

Sí, como parte de un **outbox pattern**, pero con matices:

- `SBO_SP_PostTransactionNotice` se ejecuta **después** del commit. No puede
  revertir la transacción.
- `SBO_SP_TransactionNotification` se ejecuta **antes** del commit y puede
  bloquear/rollback; **no** se debe usar para llamadas HTTP lentas.
- El post-transaction notice es ideal para **insertar un evento** en una tabla,
  no para actualizar el bot directamente.
- No todos los cambios de maestro (artículos, precios, descuentos) disparan
  necesariamente el notice; hay que validar `@object_type` o usar triggers/delta.

**Regla:** el procedimiento SAP solo escribe en una tabla de eventos. El bot lee
esa tabla y actualiza su base. Nunca hacer HTTP ni procesos pesados dentro de SAP.

---

## 3. Arquitectura recomendada

```text
SAP B1
  ├─ factura/pedido/pago ──► SBO_SP_PostTransactionNotice
  ├─ artículo/precio/descuento ──► trigger/delta/webhook
  └─ ROHO_EVENT (outbox)
            │
            ▼
Bot worker (cada 30–60 s)
  ├─ lee eventos nuevos por watermark
  ├─ consulta Service Layer del registro afectado
  ├─ upsert idempotente en PostgreSQL
  └─ guarda watermark / errores
            │
            ▼
Catálogo, promociones, compras, perfil
```

Mantener el full sync nocturno como **reconciliación** y respaldo.

---

## 4. Tabla de eventos en SAP

Ejemplo SQL Server:

```sql
CREATE TABLE ROHO_EVENT (
    EventID      BIGINT IDENTITY(1,1) PRIMARY KEY,
    EventType    VARCHAR(50)  NOT NULL,  -- invoice.created, item.updated, price.updated
    EntityKey    VARCHAR(100) NOT NULL,  -- DocEntry, ItemCode, CardCode
    Payload      NVARCHAR(MAX) NULL,     -- JSON/XML opcional
    CreatedAt    DATETIME     NOT NULL DEFAULT GETDATE(),
    Source       VARCHAR(30)  NOT NULL DEFAULT 'SAP'
);

CREATE INDEX IX_ROHO_EVENT_ID ON ROHO_EVENT(EventID);
```

Ventajas:

- El bot lee por `EventID > último_visto`, sin escribir en SAP.
- No necesita marcar `processed` en SAP.
- Si el bot está caído, los eventos quedan y se procesan al volver.

---

## 5. Post-transaction notice (pseudocódigo)

```sql
-- SBO_SP_PostTransactionNotice
-- Solo insertar; nunca lanzar error ni hacer HTTP.
IF @object_type IN ('13', '17', '24')  -- factura, pedido, pago
BEGIN
    INSERT INTO ROHO_EVENT(EventType, EntityKey, Payload)
    VALUES (
        CASE @object_type
            WHEN '13' THEN 'invoice.created'
            WHEN '17' THEN 'order.created'
            WHEN '24' THEN 'payment.created'
        END,
        CAST(@list_of_cols_val_tab_del AS VARCHAR(100)),
        NULL
    );
END
```

Validar los códigos de `@object_type` y la firma exacta en la versión de SAP B1
instalada. Para master data, evaluar triggers sobre `OITM`, `ITM1`, `OSPP`,
`SPP1` o un delta por fecha.

---

## 6. Poller del bot

1. Leer `GET /ROHO_EVENT?$filter=EventID gt {watermark}&$orderby=EventID&$top=100`.
2. Para cada evento:
   - `invoice.*` → `Invoices(DocEntry)` → upsert `purchase_history`.
   - `item.*` → `Items('SKU')` → upsert catálogo.
   - `price.*` / `promotion.*` → `SpecialPrices` del SKU → upsert promociones.
   - `payment.*` → estado del pedido.
3. Guardar `last_event_id` en PostgreSQL.
4. Reintentos con backoff; errores a una tabla `sap_event_dead_letter`.
5. Full sync nocturno para reconciliar.

---

## 7. Alternativas

| Opción | Cuándo |
|---|---|
| **Service Layer webhooks** | Si la versión de SAP B1 los soporta; es la vía más limpia |
| **Post-transaction notice + outbox** | Documentos; buena latencia y bajo acoplamiento |
| **Triggers SQL** | Master data; requiere DBA y cuidado en upgrades |
| **Delta por `UpdateDate`** | Si el campo existe y es confiable; menos invasivo |
| **Full sync nocturno** | Reconciliación; ya implementado |

---

## 8. Recomendación

1. Empezar por **facturas/pedidos/pagos** con post-transaction notice + outbox.
2. Para **artículos/precios/descuentos**, usar delta o triggers solo si el DBA
   lo aprueba; mientras tanto, dejar la sync cada 6 h.
3. Poller cada 30–60 s con watermark e idempotencia.
4. Full sync nocturno como red de seguridad.
5. Métricas: eventos pendientes, antigüedad del último evento, errores, latencia.

No conviene hacer que el bot consulte SAP cada mensaje para todo: el Service
Layer tiene límites y la latencia se dispara. El outbox da cercanía a tiempo real
sin ese costo.

---

## 9. ¿Hace falta RAG?

**No para el núcleo transaccional.** Precios, stock, descuentos, pedidos e
historial son datos estructurados: se consultan con SQL/Service Layer y deben ser
exactos. Meterlos en embeddings añade latencia, costo y riesgo de respuestas
desactualizadas.

El flujo correcto es:

```text
Outbox SAP → worker → PostgreSQL (tablas estructuradas)
                              ↓
                    herramientas del agente (SQL)
                              ↓
                    precio/stock/promo exactos
```

**RAG sí puede aportar en:**

- búsqueda semántica de productos por descripción (“algo para regar plantas”),
- políticas de envío, devoluciones, garantía,
- preguntas frecuentes,
- manuales y cuidados de productos,
- contenido de marketing.

En esos casos se puede usar PostgreSQL con `pgvector` + `pg_trgm`/full-text,
sin necesidad de una base vectorial separada. El resultado semántico siempre se
cruza después con precio/stock reales en SQL.

**Regla:** RAG para texto; SQL para hechos comerciales.
