# Pendientes del proyecto

**Actualizado:** 19-oct-2026

## P0 — Actualización event-driven de SAP

**Estado:** consumidor del bot implementado; publisher del integrador agregado
detrás de `Outbox:PublishEvents=false`. Falta activar RabbitMQ y validar
end-to-end.

**Objetivo:** que una factura, artículo, precio o descuento nuevo se refleje en el
bot en segundos/minutos, no en horas.

**Diseño:** [actualizacion-sap-eventos.md](actualizacion-sap-eventos.md).

### Alcance

1. Tabla `ROHO_EVENT` en SAP (outbox).
2. `SBO_SP_PostTransactionNotice` para facturas, pedidos y pagos.
3. Poller en el worker con watermark (`last_event_id`).
4. Upsert idempotente:
   - factura → `purchase_history`
   - artículo → `catalog_items`
   - precio/descuento → `product_promotions`
5. Reintentos, dead-letter y métricas.
6. Full sync nocturno como reconciliación.

### Dependencias

- DBA/consultor SAP para crear la tabla y el procedimiento.
- Validar `@object_type` de la versión de SAP B1.
- Definir si artículos/precios usan trigger, delta o webhook.
- Usuario de integración **solo lectura** para el bot.

### Criterios de aceptación

- Factura nueva visible en el historial en menos de 60 s.
- Artículo/precio nuevo visible en menos de 5 min.
- El procedimiento SAP no hace HTTP ni procesos pesados.
- El bot no escribe en SAP.
- Si el bot está caído, los eventos se procesan al volver.
- Un full sync nocturno corrige cualquier diferencia.

### Implementado

- Consumidor `app/events/consumer.py` + `sap_event_inbox`.
- Handler `4` (item) y `13` (factura).
- Publisher `ISapEventPublisher` en el integrador, flag `Outbox:PublishEvents`.
- Cola `chatbot.sap.events` + DLQ + reintentos.
- Prueba local con `scripts/publish_test_event.py`.

### Siguiente paso

Activar `Outbox:PublishEvents=true` en QA, levantar RabbitMQ y probar un evento
real de factura/artículo end-to-end.

---

## P1 — Producción

- **Catálogo/carrito nativo**: adaptador, payloads, feed CSV y parser de pedidos
  listos; falta número de producción y catálogo en Commerce Manager.
- **PostgreSQL**: migraciones Alembic listas; falta cambiar `DATABASE_URL`,
  correr `alembic upgrade head` y migrar datos.
- **Redis**: mover caché de precio/stock y garantizar cola/worker.
- **Rate limiting** por contacto, especialmente para búsqueda por carnet.
- **Observabilidad**: trazas, métricas, errores y costo por conversación.
- **Cifrado de PII** y política de retención.
- **WhatsApp producción**: número, verificación, plantillas y ventana de 24 h.
- **CUCU**: API key, webhook secret y conciliación de pagos.

## P2 — Comercial

- Segmentos: nuevo, recurrente, alto valor, inactivo.
- Campañas con plantillas aprobadas y opt-in.
- **Base de conocimiento**: carpeta `knowledge/` y herramienta implementadas;
  falta completar envíos, garantías, devoluciones, tiendas y pagos, y pasarlos a
  `published`.
- **Precio único**: `app/services/pricing.py` implementado; falta validar que
  búsqueda, ficha y carrito muestren el mismo final en producción.
- **Búsqueda**: sinónimos, intención de categoría y corrección de typos
  implementados; falta full-text real en PostgreSQL.
- **Imágenes**: tabla `product_images`, importador CSV, 25 imágenes reales ROHO
  y placeholders demo implementados; falta CDN propio y derechos de uso.
- **Carrito**: agregar, quitar, cambiar cantidad y vaciar implementados.
  Carrito nativo preparado para reemplazo desde pedido de WhatsApp; falta
  número de producción y catálogo aprobado.
- **Webhook**: estado en `/admin/webhook/status`, tabla `webhook_events` y
  `scripts/check_webhook.py` implementados; falta dominio/túnel estable y alerta
  automática.
- **Botones/listas**: saludo contextual, búsqueda, filtros por precio y
  acciones de carrito implementados; falta paginación real y lista de tiendas.
- **Frontend**: consola React/Vite con paleta rojo-azul-negro-blanco, login,
  bandeja, filtros, búsqueda, plantillas, notas, adjuntos entrantes/salientes,
  leído/no leído y SSE; falta dominio estable y roles más finos.
- **Handoff**: login por asesor, bandeja, SLA, guardia, administración de
  agentes, notificaciones visibles, contexto y auditoría implementados; falta
  helpdesk completo y roles finos.
- **Feedback**: ciclo de atención/entrega, dashboard API y envío saliente con
  plantilla (detrás de flag) implementados; falta aprobar plantilla.
- **Entrega**: el bot no debe gestionar logística; solo reaccionar a un evento
  `delivery` de SAP/logística o a una marcación manual.
- **Más vendidos**: modelo, script y herramienta listos; falta correr
  `sync_sales_stats` contra SAP y validar en QA.
- Score de recomendación con rotación, margen y ticket.
- Carrito abandonado y win-back.
- Sync incremental de compras (hoy hasta 100 facturas por cliente).
- Validar identificación por carnet con clientes reales y OTP opcional.
- **RAG opcional** para búsqueda semántica de productos y documentos (políticas,
  garantías, FAQs). No usar RAG para precios, stock, promociones ni compras.

## P3 — Operación

- Backups y restauración probada.
- CI con tests + `alembic check`.
- Alertas de eventos atrasados y errores SAP.
- Documentación de runbook.
