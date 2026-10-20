# Chatbot WhatsApp + SAP Business One

Scaffold funcional de un chatbot B2C para WhatsApp Cloud API, con catálogo, carrito,
pedido en SAP Business One, pago por QR (mock) y facturación automática al confirmar
el pago.

- **Canal:** WhatsApp Cloud API (webhook verificado con HMAC).
- **IA:** DeepSeek con *tool calling*; si no hay API key, usa un agente demo determinista.
- **SAP:** Service Layer (OData) con adaptador real y `mock` para desarrollar sin SAP.
- **Pagos:** proveedor mock con página de QR y confirmación simulada.
- **Stack:** FastAPI + PostgreSQL + Redis + Arq + SQLAlchemy async.

Documentos:

- [Arquitectura y roadmap](docs/arquitectura-chatbot-whatsapp-sap-b1.md)
- [Flujo actual de la aplicación](docs/flujo-actual.md)
- [Cómo hacer que el agente venda](docs/agente-vendedor.md)
- [Memoria, historial y recomendaciones](docs/evolucion-agente.md)
- [Identificación y onboarding del cliente](docs/identificacion-cliente.md)
- [Actualización periódica y eventos SAP](docs/actualizacion-sap-eventos.md)
- [Cambiar el número y habilitar catálogo/carrito](docs/migracion-numero-catalogo.md)
- [Alta del número de producción](docs/alta-numero-produccion.md)
- [Migrar un número On-Premises a Cloud API](docs/migracion-onprem-cloud.md)
- [Reutilizar el integrador PAAS](docs/integrador-paas.md)
- [Consumidor de eventos SAP](docs/consumidor-eventos-sap.md)
- [Foco comercial: productos, precios y clientes](docs/foco-comercial.md)
- [Base de conocimiento en archivos](docs/base-conocimiento.md)
- [Botones y listas en WhatsApp](docs/botones-listas.md)
- [Búsqueda de productos](docs/busqueda-productos.md)
- [Handoff a asesores](docs/handoff.md)
- [Carrito editable y nativo](docs/carrito.md)
- [Monitoreo del webhook](docs/monitoreo-webhook.md)
- [Consola de asesores React](docs/admin-web.md)
- [Despliegue Docker / Render / Railway](docs/despliegue.md)
- [Integración bot ↔ integration-paas](docs/integracion-paas-bot.md)
- [Imágenes de productos](docs/imagenes-productos.md)
- [Catálogo y carrito nativo: adaptación](docs/catalogo-carrito-nativo.md)
- [Fallback comercial y feedback](docs/feedback-y-recomendaciones.md)
- [Plantilla de encuesta de entrega](docs/plantillas-whatsapp.md)
- [Pendientes del proyecto](docs/pendientes.md)
- [Configuración de Meta paso a paso](docs/configuracion-meta.md)
- [Estrategia de catálogo SAP (65k artículos)](docs/estrategia-catalogo-sap.md)
- [Pagos QR Simple con CUCU](docs/pagos-qr-cucu.md)
- [Prueba de escritura en SAP QA](docs/escritura-sap-qa.md)

---

## Arranque rápido (Docker)

```powershell
# Sólo si todavía no tienes .env (no sobrescribas el que ya tiene credenciales)
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build
```

- API y documentación: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Postgres y Redis se publican en `localhost:5433` y `localhost:6380` para no chocar
  con instalaciones locales. Dentro de Docker se usan `db:5432` y `redis:6379`.
- Catálogo: con `SEED_DEMO=true` carga 24 productos demo; para datos reales,
  ejecuta `scripts/sync_catalog.py`.
- `WA_DRY_RUN=true` por defecto: no se llama a Meta, las respuestas se registran en
  logs y en la base.

### Sin Docker (SQLite)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
$env:QUEUE_ENABLED = "false"
uvicorn app.main:app --reload
```

---

## Base de datos y escalabilidad

- **SQLite** (`.env` local) sirve para desarrollar y para una sola instancia. No
  debe usarse con varios workers ni como base de producción.
- **PostgreSQL** es la base recomendada (Docker Compose ya la incluye). El código
  usa SQLAlchemy async; se cambia con `DATABASE_URL`.
- `AUTO_CREATE_DB=true` usa `create_all` para desarrollo. En producción se pone
  `false` y se aplican migraciones con **Alembic**:

```powershell
alembic upgrade head          # aplica migraciones
alembic revision --autogenerate -m "cambio"
alembic check                 # verifica que no falten cambios
```

- La migración inicial fue probada en **PostgreSQL 18** con
  `alembic upgrade head` y `alembic check` sin diferencias.
- La API es stateless; la cola es Redis/Arq; los workers escalan aparte.
- Las cachés de precio/stock son en memoria por proceso. Con varios workers,
  conviene moverlas a Redis para compartirlas.
- SAP Service Layer sigue siendo el cuello: 20 filas por página, sesión de 30 min.
  Por eso el catálogo/promociones se sincronizan y no se consultan por mensaje.

---

## Probar la conversación sin WhatsApp

`POST /dev/simulate` inyecta un mensaje como si viniera de Meta y devuelve las
respuestas del bot. Secuencia sugerida:

```powershell
$sim = { param($text) Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/dev/simulate -ContentType 'application/json' `
  -Body (@{ wa_id = '59179462889'; text = $text; name = 'Ana' } | ConvertTo-Json) }

$sim.Invoke('hola')                 # menú
$sim.Invoke('buscar filtro')        # catálogo
$sim.Invoke('agregar FILT-001 2')   # carrito
$sim.Invoke('carrito')              # totales
$sim.Invoke('checkout')             # pedido + link de pago
$sim.Invoke('estado')               # estado del pedido
```

`checkout` devuelve una URL como `http://localhost:8000/mock/pay/<id>`. Ábrela:
muestra el QR, el resumen y el botón **Confirmar pago (simulado)**. Al confirmar:

1. el pago pasa a `paid`,
2. se crea la factura en SAP (mock),
3. se registra el cobro relacionado (`IncomingPayments`),
4. el pedido pasa a `invoiced`,
5. se envía el mensaje de confirmación por WhatsApp (dry-run).

En WhatsApp real, el bot envía el link con un botón CTA "Pagar con QR".

---

## Conectar WhatsApp Cloud API

1. Crear app Business en <https://developers.facebook.com>, agregar el producto
   WhatsApp y vincular la WABA.
2. Configurar en `.env`:
   - `WA_PHONE_NUMBER_ID`
   - `WA_ACCESS_TOKEN` (token permanente de un system user)
   - `WA_APP_SECRET`
   - `WA_VERIFY_TOKEN`
   - `WA_DRY_RUN=false`
3. Exponer el webhook por HTTPS (Cloudflare Tunnel, ngrok o un dominio con TLS).
   Ajusta `PUBLIC_BASE_URL` a esa URL pública: el link de pago se abre desde el
   teléfono del cliente, así que `localhost` no sirve en producción.
4. En Meta, configurar la URL `https://<dominio>/webhooks/whatsapp` con el mismo
   `WA_VERIFY_TOKEN` y suscribir el campo `messages`.
5. Probar con el número de prueba de Meta (hasta 5 destinatarios) antes de usar el
   número de producción.

> **Número +591 79462889:** está configurado en `.env` (no versionado). Si hoy
> está registrado en WhatsApp Consumer o en la app WhatsApp Business, la Cloud API
> no lo puede usar tal cual: hay que migrarlo/eliminarlo o evaluar la coexistencia.
> Verifica esto antes de intentar registrarlo.

Checklist completo: sección 2.1 del documento de arquitectura.

---

## Conectar SAP Business One 10 (on-premise)

Probado contra el ambiente **RETAIL_QA** (`hanaroda25.gruporoda.com`): login,
lectura de artículos, precios y stock. El adaptador `ServiceLayerSap` implementa:

- login con `B1SESSION`/`ROUTEID` y renovación ante `401`; en esta instalación el
  `SessionId` viene en el body del login, no en la cookie,
- `GET /Items('SKU')` para precio y stock del almacén configurado,
- alta/búsqueda de socio por teléfono (`WA` + últimos 10 dígitos),
- `POST /Orders` (deja que SAP calcule impuestos y total),
- `POST /Invoices` con `BaseType: 17` (pedido → factura),
- `POST /IncomingPayments` aplicado a la factura.

Para activarlo:

```env
SAP_MODE=service_layer
SAP_SL_URL=https://hanaroda25.gruporoda.com/b1s/v1
SAP_COMPANY_DB=RETAIL_QA
SAP_USER=...
SAP_PASSWORD=...
# El servidor QA usa certificado autofirmado. En producción instala la CA
# corporativa y deja SAP_VERIFY_TLS=true.
SAP_VERIFY_TLS=false
SAP_WAREHOUSE=101-1001
SAP_PRICE_LIST=1
SAP_CASH_ACCOUNT=
SAP_STORES=101-1001=Tienda 1,102-1001=Tienda 2,103-1001=Tienda 3
SAP_PRICE_CACHE_TTL_SECONDS=300
# Lectura en vivo con caché de 60 s; escritura desactivada hasta validar QA.
SAP_LIVE_READS=true
SAP_WRITE_ENABLED=false
SAP_CACHE_TTL_SECONDS=60
```

Modos:

| Configuración | Comportamiento |
|---|---|
| `SAP_MODE=mock` | Todo local; no toca SAP |
| `SAP_MODE=service_layer` + `SAP_LIVE_READS=true` + `SAP_WRITE_ENABLED=false` | Precio/stock en vivo con caché; checkout mock |
| `SAP_MODE=service_layer` + `SAP_WRITE_ENABLED=true` | Pedido, factura y cobro reales en SAP |

La búsqueda siempre es local (rápida). La ficha, el carrito y el checkout
refrescan contra SAP; el checkout fuerza la lectura (`force_refresh`) para no
cobrar con un precio viejo.

### Precios, descuentos y stock por tienda

- **Stock**: se lee de `ItemWarehouseInfoCollection` para Tienda 1
  (`101-1001`), Tienda 2 (`102-1001`) y Tienda 3 (`103-1001`).
- **Precio base**: lista de precios configurada (`SAP_PRICE_LIST`).
- **Descuentos por período/cantidad**: se leen de `SpecialPrices` para el SKU
  consultado, con caché de `SAP_PRICE_CACHE_TTL_SECONDS` (300 s).
- **Cálculo**: se elige el período vigente más reciente y, dentro de él, el
  escalón de cantidad más alto que no supere la cantidad pedida.
- El carrito guarda tienda, precio de lista, descuento y precio final; el
  checkout revalida todo contra SAP.

La herramienta `get_product` del agente acepta `quantity` y devuelve
`base_price`, `final_price`, `discount_percent`, `stock_by_store` y vigencia.
`add_to_cart` acepta `store` (`101-1001`, `102-1001`, `103-1001`).

Para que el agente pueda **sugerir promociones** sin preguntar por un SKU, se
sincroniza `product_promotions` desde `SpecialPrices`:

```powershell
python -m scripts.sync_promotions
```

La herramienta `list_promotions` devuelve promociones vigentes con descuento,
ordenadas y diversificadas por categoría. El prompt del agente tiene un rol
comercial (descubrir necesidad, recomendar, mencionar vigencia y cerrar). Ver
[`docs/agente-vendedor.md`](docs/agente-vendedor.md).

Recomendaciones:

- Probar primero contra la empresa de pruebas y con un usuario de permisos mínimos.
- Validar en SAP la numeración, impuestos, almacén y forma de pago antes de facturar.
- **No** exponer el puerto 50000 a Internet: el backend debe vivir en la misma red o
  usar VPN/túnel.
- El mock de SAP está en `app/sap.py` (`MockSap`) y se activa con `SAP_MODE=mock`.

### Sincronizar el catálogo

El bot **no** consulta el Service Layer por cada mensaje: sincroniza el catálogo a
Postgres/SQLite y busca localmente. SAP sigue siendo la verdad para precio/stock al
crear el pedido.

```powershell
# Prueba con 100 artículos en SQLite
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
python -m scripts.sync_catalog --limit 100

# Catálogo completo (~29.700 artículos vendibles; tarda unos minutos)
python -m scripts.sync_catalog --deactivate-missing

# Promociones vigentes (SpecialPrices) para que el agente pueda sugerirlas
python -m scripts.sync_promotions

# Historial de compras de un cliente (por CardCode de SAP)
python -m scripts.sync_purchases --card-code VTX000019 --wa-id 59170000110
python -m scripts.sync_purchases --all

# Estadísticas de ventas / más vendidos (90 días)
python -m scripts.sync_sales_stats --days 90

# Encuestas de feedback vencidas (requiere plantilla aprobada)
python -m scripts.send_feedback_surveys

# Si usas Docker/Postgres
docker compose exec api python -m scripts.sync_catalog --deactivate-missing
docker compose exec api python -m scripts.sync_promotions
docker compose exec api python -m scripts.sync_purchases --all
```

Qué hace:

- trae grupos y fabricantes para mapear categorías/marcas,
- pagina `Items` con `Valid=tYES`, `SalesItem=tYES`, `ItemType=itItems`,
- upsert por `sku`, precio de `SAP_PRICE_LIST`, stock, sinónimos y `synced_at`,
- omite artículos sin precio o sin nombre.

Detalle y hallazgos del catálogo real (65.094 artículos, 29.731 vendibles,
paginación de 20) en [`docs/estrategia-catalogo-sap.md`](docs/estrategia-catalogo-sap.md).

---

## Pagos QR

Dos modos:

- **`mock_qr`** (por defecto): QR local y botón “Confirmar pago (simulado)”. No
  mueve dinero; sirve para probar el flujo completo.
- **`cucu_qr`**: integración con el sandbox/producción de **QR Simple de CUCU**
  (`POST /qr`, webhook `qr.paid` firmado con Standard Webhooks).

```env
PAYMENT_PROVIDER=cucu_qr
CUCU_API_KEY=...
CUCU_WEBHOOK_SECRET=whsec_...
```

El webhook se registra en `https://<dominio>/webhooks/payments/cucu`. Guía
completa: [`docs/pagos-qr-cucu.md`](docs/pagos-qr-cucu.md).

En ambos modos el flujo es el mismo: pedido en SAP → QR → pago → factura +
`IncomingPayments` → notificación por WhatsApp. Lo único que cambia es quién
confirma el pago.

---

## Flujo de pedido

```text
carrito (Postgres)
  └─ checkout
       ├─ revalida precio/stock contra SAP
       ├─ POST /Orders  → DocEntry + DocTotal (SAP manda)
       ├─ crea Payment (pending) + QR/link
       └─ cliente paga
            ├─ webhook/confirmación firmada (idempotente)
            ├─ POST /Invoices (BaseType 17)
            ├─ POST /IncomingPayments
            └─ pedido invoiced + notificación WhatsApp
```

Estados: `pending_payment → paid → invoiced` (o `cancelled`).

---

## Estructura

```text
app/
  api.py            webhooks, pago mock, panel y demo
  agent.py          agente DeepSeek + tools + agente demo
  config.py         settings por variables de entorno
  db.py             engine/sesiones async
  main.py           FastAPI + lifespan + seed
  models.py         contactos, conversaciones, carrito, pedidos, pagos, catálogo
  runtime.py        cliente WhatsApp + agente compartidos
  sap.py            interfaz SapAdapter + MockSap + ServiceLayerSap
  seed.py           24 productos demo
  services/
    cart.py         carrito y totales
    catalog.py      búsqueda (scaffold: ILIKE; producción: FTS + pgvector)
    ingest.py       dedupe, historial, agente, envío y persistencia
    orders.py       checkout, pago, factura, cobro
  whatsapp.py       envío Cloud API + parseo de mensajes + HMAC
  worker.py         Arq worker
scripts/
  sync_catalog.py   sincronización SAP → catálogo local
  sync_promotions.py sincronización SAP SpecialPrices → promociones locales
  sync_purchases.py  facturas SAP → historial de compras por cliente
  sync_sales_stats.py facturas SAP → más vendidos por SKU
  import_images.py   CSV SKU → URL de imagen
  import_roho_images.py imágenes reales del catálogo público ROHO
  create_advisor.py crea usuario de la bandeja
  load_demo_images.py placeholders por categoría para demo
  export_meta_catalog.py catálogo local → CSV para Commerce Manager
  publish_test_event.py evento SAP de prueba → RabbitMQ
  send_feedback_surveys.py envía encuestas vencidas (plantilla aprobada)
docs/
  arquitectura-chatbot-whatsapp-sap-b1.md
  flujo-actual.md
  agente-vendedor.md
  evolucion-agente.md
  identificacion-cliente.md
  actualizacion-sap-eventos.md
  migracion-numero-catalogo.md
  alta-numero-produccion.md
  migracion-onprem-cloud.md
  integrador-paas.md
  consumidor-eventos-sap.md
  foco-comercial.md
  base-conocimiento.md
  botones-listas.md
  busqueda-productos.md
  handoff.md
  carrito.md
  monitoreo-webhook.md
  admin-web.md
  imagenes-productos.md
  catalogo-carrito-nativo.md
  feedback-y-recomendaciones.md
  plantillas-whatsapp.md
  pendientes.md
  configuracion-meta.md
  estrategia-catalogo-sap.md
  escritura-sap-qa.md
  pagos-qr-cucu.md
tests/
  test_cart_checkout.py
  test_webhook.py
  test_whatsapp_parse.py
alembic/
  env.py
  versions/         migraciones
alembic.ini
```

---

## Docker

```bash
docker compose up -d --build
```

API y consola:

```text
http://localhost:8000/console/
```

PostgreSQL queda en un volumen Docker. Ver [docs/despliegue.md](docs/despliegue.md).

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Cubren: carrito y stock, checkout, confirmación de pago, factura/cobro, idempotencia,
verificación HMAC, deduplicación de webhooks, verificación de Meta y endpoint demo.

---

## Modo demo vs producción

| Variable | Demo | Producción |
|---|---|---|
| `WA_DRY_RUN` | `true` | `false` |
| `WA_APP_SECRET` | vacío | obligatorio |
| `DEEPSEEK_API_KEY` | vacío (agente demo) | obligatorio |
| `SAP_MODE` | `mock` | `service_layer` |
| `QUEUE_ENABLED` | `false` | `true` |
| `PAYMENT_PROVIDER` | `mock_qr` | `cucu_qr` |
| `ADMIN_TOKEN` | vacío | obligatorio |

En producción además: HTTPS, secret manager, backups, `ADMIN_TOKEN`, rotación de
tokens y monitoreo de quality rating de la WABA.

---

## Siguientes pasos

1. **Onboarding Meta**: verificación de negocio, número, display name, plantillas
   (guía: [`docs/configuracion-meta.md`](docs/configuracion-meta.md)).
2. **Catálogo**: dejar la sync completa programada y definir lista de precios,
   almacén, promociones e imágenes ([`docs/estrategia-catalogo-sap.md`](docs/estrategia-catalogo-sap.md)).
3. **Búsqueda híbrida**: full-text español + `pg_trgm` + `pgvector` + reranking
   (hoy es ILIKE y alcanza para probar, no para 30k artículos).
4. **Validar escritura SAP** (pedido, factura, cobro) en RETAIL_QA y definir serie,
   impuestos, almacén y forma de pago.
5. **Pasarela real** (Libélula/QR Simple) reemplazando `mock_qr`, con webhook firmado.
6. **WhatsApp Flows** para catálogo/carrito nativo y checkout más guiado.
7. **Panel de agentes** (Next.js) para handoff, catálogo y métricas.
8. **Plantillas** de confirmación, pago y envío; job de reconciliación de pagos.
9. **Audios**: transcripción con Whisper (hoy se ignoran).

---

## Notas de seguridad

- Nunca se piden datos de tarjeta por chat; el pago va por link/QR.
- El monto se recalcula en servidor y SAP es la fuente de verdad del total.
- El webhook valida `X-Hub-Signature-256`; el mock de pago es idempotente.
- No se escribe directo a la base de SAP ni se usa DI API/COM.
- Los logs no deben contener secretos ni datos fiscales completos.

## Consola de asesores

El frontend React vive en `admin-web/`.

```powershell
cd admin-web
pnpm install
pnpm build:console
```

El API sirve la consola en:

```text
http://127.0.0.1:8000/console/
```

Rutas:

```text
/console/login
/console/inbox
/console/agents
/console/metrics
```

Para desarrollo con Vite:

```powershell
pnpm dev
```

El proxy de Vite envía `/advisor`, `/admin` y `/api` a `http://127.0.0.1:8000`.

No uses `pnpm build` para producción si la consola se sirve bajo `/console/`:
usá `pnpm build:console`, que genera los assets con el prefijo correcto.
