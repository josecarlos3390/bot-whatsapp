# Integración bot ↔ integration-paas

## Estado

- PaaS local en `http://127.0.0.1:5000`.
- Tenant local `chatbot`, empresa `RETAIL_QA5`.
- Service Layer: `https://hanaroda25.gruporoda.com:50000`.
- Prueba real OK: `AIRACCE010005`, precio `149`, stock `1`.
- Bot en `SAP_MODE=paas`.
- Endpoints de lectura agregados.
- Eventos: publisher del worker activado y consumer del bot activo.
- Escrituras SAP (factura/pago) todavía pendientes.

## API PaaS usada

Autenticación:

```http
X-Api-Key: <tenant-api-key>
```

Lecturas:

```http
GET /api/sap/items/{sku}
GET /api/sap/business-partners/{cardCode}
```

Pedido existente:

```http
POST /api/crm/orders
```

El PaaS gestiona la sesión SAP; el bot no recibe credenciales SAP.

## Configuración del bot

```env
SAP_MODE=paas
SAP_PAAS_URL=http://127.0.0.1:5000
SAP_PAAS_API_KEY=...
SAP_PAAS_TENANT=tenant-001
```

## Eventos

```env
SAP_EVENT_QUEUE_ENABLED=true
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
SAP_EVENT_EXCHANGE=sap.events
SAP_EVENT_QUEUE=chatbot.sap.events
SAP_EVENT_DLQ=chatbot.sap.events.dlq
SAP_EVENT_DLX=chatbot.sap.events.dlx
SAP_EVENT_TENANT=tenant-001
```

PaaS:

```json
"Outbox": {
  "PublishEvents": true,
  "EventExchange": "sap.events"
}
```

El bot consume, deduplica por `event_id` y escribe en `sap_event_inbox`.
Actualmente procesa artículos (`4`) y facturas (`13`). Pedidos (`17`) y
listas de precio quedan pendientes.

## Rendimiento

Prueba local del endpoint de artículo:

- primera llamada: ~9 s (login SAP + consulta),
- llamadas siguientes: ~1.8–3 s,
- respuesta filtrada por tiendas: solo las tiendas configuradas.

El bot mantiene una caché de 60 s por SKU. Para búsquedas se usa el catálogo
local; PaaS se consulta al ver ficha, precio o stock. No conviene llamar a PaaS
por cada mensaje ni recorrer el catálogo completo.

Recomendaciones:

1. Caché de 30–60 s en PaaS.
2. Sincronización masiva por eventos o proceso nocturno.
3. Endpoint batch para precios/stock.
4. Timeout y fallback local para lecturas.
5. Escrituras solo con idempotencia.

## Escrituras

El endpoint `/api/crm/orders` existe y crea pedidos en SAP. Para el bot falta:

1. endpoint de factura,
2. endpoint de pago,
3. mapeo de `Order` del bot al `CrmOrderPayload`,
4. idempotencia por `order.number`.

Mientras tanto:

```env
SAP_WRITE_ENABLED=false
```

## Prueba

```powershell
# API PaaS
dotnet run --project D:\ProyectosPython\integrator-paas\src\Integration.Api

# Bot
SAP_MODE=paas .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Verificar:

```http
GET http://127.0.0.1:5000/health/ready
GET http://127.0.0.1:5000/api/sap/items/{sku}
```
