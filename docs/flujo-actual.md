# Flujo actual de la aplicación

**Estado:** 19-oct-2026 · WhatsApp Cloud API + DeepSeek + SAP Business One 10 (QA)

---

## 1. Vista general

```mermaid
flowchart LR
    C[Cliente en WhatsApp] -->|mensaje| M[Meta Cloud API]
    M -->|POST webhook| A[FastAPI]
    A -->|HMAC + dedupe| Q{¿Cola activa?}
    Q -->|sí| R[(Redis / Arq)]
    Q -->|no| W[Worker en proceso]
    R --> W
    W --> G[Agente DeepSeek]
    G --> T[Herramientas]
    T --> CAT[(Catálogo local)]
    T --> SAP[SAP Service Layer]
    T --> CART[(Carrito SQLite/Postgres)]
    T --> PAY[Pago mock QR]
    G -->|respuesta| M
    M --> C
    PAY --> INV[Factura + cobro mock]
```

---

## 2. Secuencia de un mensaje

```mermaid
sequenceDiagram
    participant C as Cliente
    participant M as Meta
    participant A as FastAPI
    participant Q as Cola
    participant W as Worker
    participant G as Agente
    participant S as SAP
    participant DB as Base local

    C->>M: "busco macetas"
    M->>A: POST /webhooks/whatsapp
    A->>A: valida firma + dedupe
    A-->>M: 200 OK
    A->>Q: encola (o procesa inline)
    Q->>W: mensaje
    W->>DB: contacto, historial
    W->>G: texto + historial
    G->>DB: search_products
    DB-->>G: 5 resultados
    G->>S: get_offer(SKU, cantidad)
    S-->>G: precio, descuento, stock por tienda
    G->>M: respuesta (texto/botones/CTA)
    M->>C: mensaje
```

Detalles:

- El webhook valida `X-Hub-Signature-256` y deduplica por `message.id`.
- Responde `200` rápido; si `QUEUE_ENABLED=true`, el trabajo va a Redis/Arq.
- El agente usa DeepSeek en modo **no-thinking** para bajar latencia.
- El historial se guarda en `messages`; el contexto enviado al LLM son los últimos 10 mensajes.

---

## 3. Ficha de producto, precio y stock
```mermaid
sequenceDiagram
    participant G as Agente
    participant H as HybridSap
    participant C as Caché
    participant S as Service Layer
    participant DB as Catálogo local

    G->>H: get_offer(SKU, cantidad)
    H->>C: precio/stock (TTL 60 s)
    alt cache fresco
        C-->>H: SapItem
    else cache vencida o force_refresh
        H->>S: GET Items('SKU')
        S-->>H: precio + stock por almacén
        H->>S: GET SpecialPrices?$filter=ItemCode...
        S-->>H: períodos y escalones
        H->>C: guarda (TTL 60 s / 300 s)
    end
    H->>H: elige período vigente y escalón
    H-->>G: precio base, final, dto., stock por tienda
    opt SAP falla y no es checkout
        H->>DB: fallback catálogo local
    end
```

Reglas:

- Tiendas: `101-1001` (Tienda 1), `102-1001` (Tienda 2), `103-1001` (Tienda 3).
- Stock: `InStock - Committed` por almacén.
- Precio: lista `SAP_PRICE_LIST` (1).
- Descuento: `SpecialPrices` → período vigente → escalón de cantidad.
- Caché de artículo: 60 s. Caché de precios especiales: 300 s.
- Checkout usa `force_refresh=True`: no acepta caché.

## 3.1 Listar promociones

```mermaid
sequenceDiagram
    participant C as Cliente
    participant G as Agente
    participant P as product_promotions
    participant S as SAP

    C->>G: "¿Qué promociones tienen?"
    G->>P: promociones vigentes con stock
    P-->>G: SKU, precio, descuento, vigencia
    G->>S: stock por tienda (solo top 5)
    S-->>G: stock 101/102/103
    G-->>C: 2-3 opciones con descuento y vigencia
```

`product_promotions` se llena con `scripts/sync_promotions.py` desde
`SpecialPrices`. Sin esa tabla el agente no puede saber qué productos tienen
descuento hasta que el cliente menciona un SKU.

---

## 4. Carrito y checkout

```mermaid
sequenceDiagram
    participant C as Cliente
    participant G as Agente
    participant DB as Carrito
    participant S as HybridSap
    participant M as MockSap
    participant P as Pago mock
    participant W as WhatsApp

    C->>G: "agrega 1 en Tienda 1"
    G->>S: get_offer(SKU, cantidad)
    S-->>G: stock tienda + precio final
    G->>DB: add_item(store, precio, dto.)
    DB-->>G: carrito
    C->>G: "confirma el pedido"
    G->>S: get_offer(force_refresh=True)
    S-->>G: precio/stock actuales
    G->>M: POST orden (mock)
    M-->>G: DocEntry mock + total
    G->>P: crea QR mock
    P-->>G: URL /mock/pay/<id>
    G->>W: CTA "Pagar con QR"
    C->>P: confirma pago simulado
    P->>M: factura + cobro mock
    P->>W: "Pago confirmado"
```

Estados: `pending_payment → paid → invoiced` (o `cancelled`).

---

## 5. Sincronización del catálogo

```mermaid
flowchart LR
    S[SAP Service Layer] -->|login B1SESSION| SYNC[scripts/sync_catalog.py]
    SYNC -->|Items paginados 20| CAT[(catalog_items)]
    SYNC -->|ItemGroups| GRP[grupos]
    SYNC -->|Manufacturers| MFR[fabricantes]
    GRP --> CAT
    MFR --> CAT
    CAT -->|búsqueda local| AGENTE[Agente]
```

- Full sync manual/nocturna; hoy hay **28.621 artículos** y **21.971 con stock > 0**.
- Paginación por `ItemCode gt ...` (keyset) para evitar `$skip` profundo.
- La búsqueda del bot no consulta SAP; usa esta copia local.

---

## 6. Qué es real y qué es mock

| Pieza | Estado actual |
|---|---|
| WhatsApp Cloud API | **Real** (token permanente, webhook firmado) |
| DeepSeek | **Real** |
| Catálogo local | **Snapshot de SAP QA** (28.621) |
| Precio/stock por SKU | **SAP en vivo** con caché |
| Carrito | **Local** (SQLite/Postgres) |
| Pedido en SAP | **Mock** (`SAP_WRITE_ENABLED=false`) |
| Factura/cobro SAP | **Mock** |
| Pago | **Mock QR** |
| Stock/promociones | **SAP en vivo** al consultar ficha/agregar/checkout |

---

## 7. Fallos y degradación

| Situación | Comportamiento |
|---|---|
| SAP no responde en ficha | Usa caché; si no hay, catálogo local |
| SAP no responde en checkout | **Bloquea** el checkout (`force_refresh`) |
| Redis no disponible | El webhook procesa inline (fallback) |
| WhatsApp rechaza envío | Se registra y el mensaje entrante queda guardado |
| Pago no confirmado | Pedido queda `pending_payment`; job de reconciliación pendiente |
| LLM falla | Responde el agente demo o un mensaje de fallback |

---

## 8. Configuración actual (sin secretos)

```env
SAP_MODE=service_layer
SAP_LIVE_READS=true
SAP_WRITE_ENABLED=false
SAP_CACHE_TTL_SECONDS=60
SAP_PRICE_CACHE_TTL_SECONDS=300
SAP_PRICE_LIST=1
SAP_WAREHOUSE=101-1001
SAP_STORES=101-1001=Tienda 1,102-1001=Tienda 2,103-1001=Tienda 3
PAYMENT_PROVIDER=mock_qr
WA_DRY_RUN=false
QUEUE_ENABLED=false
```

---

## 9. Diagrama visual

![Flujo actual del chatbot](flujo-actual.png)
