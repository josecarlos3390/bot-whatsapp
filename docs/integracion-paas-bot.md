# Integración bot ↔ integration-paas

## Estado

- PaaS local en `http://127.0.0.1:5050` (la API corre como servicio de Windows).
- Tenant local `chatbot`, empresa `RETAIL_QA5`.
- Service Layer: `https://hanaroda25.gruporoda.com:50000`.
- Prueba real OK: `AIRACCE010005`, precio `149`, stock `1`.
- Bot en `SAP_MODE=paas` con `SAP_WRITE_ENABLED=true`.
- Lecturas: artículos, precios y socios.
- Escrituras: alta de socio y alta de pedido (síncrona, con DocEntry).
- Factura y pago: el integrador todavía no los expone; el bot deja el pedido
  `paid` con la factura pendiente anotada en `orders.notes`.
- Eventos: publisher del worker activado y consumer del bot activo.

## API PaaS usada

Autenticación:

```http
X-Api-Key: <tenant-api-key>
```

Lecturas:

```http
GET /api/sap/items/{sku}
GET /api/sap/items?q={texto}&limit={n}   # búsqueda por nombre (caché en caliente)
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
SAP_PAAS_URL=http://127.0.0.1:5050
SAP_PAAS_API_KEY=...
SAP_PAAS_TENANT=RETAIL_QA5
```

## Eventos

```env
SAP_EVENT_QUEUE_ENABLED=true
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
SAP_EVENT_EXCHANGE=sap.events
SAP_EVENT_QUEUE=chatbot.sap.events
SAP_EVENT_DLQ=chatbot.sap.events.dlq
SAP_EVENT_DLX=chatbot.sap.events.dlx
SAP_EVENT_TENANT=RETAIL_QA5
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

El bot escribe por el integrador, sin credenciales SAP propias:

| Acción | Endpoint | Respuesta |
|---|---|---|
| Alta de socio | `POST /api/sap/business-partners` | `{cardCode}` |
| Alta de pedido | `POST /api/crm/orders` | `{sapDocEntry, sapDocNum}` |

Detalles de la implementación:

- `PaasSap.create_sales_order` mapea `Order` → `CrmOrderPayload` con
  `crmOrderId = order.number` (idempotencia por `NumAtCard` en SAP).
- Cada línea envía `costingCode`/`costingCode2`/`costingCode3` y `taxCode`
  (obligatorios en la localización chilena; sin ellos SAP responde
  `(17) Falta Centro de Costo en la línea`).
- El socio se crea con `WA<teléfono>` y el RUT del contacto
  (`federalTaxId`). Si el cliente no tiene RUT se usa `SAP_DEFAULT_CARD_CODE`;
  sin ese valor el checkout pide identificar al cliente.
- `create_invoice_from_order` y `create_incoming_payment` siguen sin endpoint:
  el pago se registra igual y la factura queda pendiente en `orders.notes`.

Pendiente en el integrador (requiere republicar `Integration.Api`):

1. endpoint de factura (`POST /Invoices` desde pedido) — además SAP bloquea hoy
   al usuario `jdiaz` con `-1116` por autorización de almacén;
2. endpoint de pago (`POST /IncomingPayments`).

Mientras la facturación no exista, dejarlo así:

```env
SAP_WRITE_ENABLED=true
SAP_DEFAULT_CARD_CODE=<socio consumidor final>
```

## Prueba

```powershell
# API PaaS (instancia de desarrollo en el 5051)
dotnet run --project C:\ProyectosPython\integrator-paas\src\Integration.Api -- --urls http://127.0.0.1:5051

# Bot apuntando a esa instancia
$env:SAP_PAAS_URL="http://127.0.0.1:5051"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
```

Verificar:

```http
GET http://127.0.0.1:5050/health/ready
GET http://127.0.0.1:5050/api/sap/items/{sku}
POST http://127.0.0.1:5050/api/sap/business-partners
POST http://127.0.0.1:5050/api/crm/orders
```
