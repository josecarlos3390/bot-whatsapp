# Estrategia de catálogo: SAP Business One → WhatsApp

Decisiones para 65.000 artículos en SAP B1 10 (RETAIL_QA) sin saturar el Service
Layer ni la conversación.

---

## 1. Lo que encontramos en el ambiente QA

Consultas de sólo lectura contra `https://hanaroda25.gruporoda.com/b1s/v1`:

| Consulta | Resultado |
|---|---|
| Artículos totales | **65.094** |
| `Valid = tYES` | 32.438 |
| `SalesItem = tYES` | 57.667 |
| `Valid + SalesItem + ItemType = itItems` | **29.731** |
| `Valid + SalesItem + stock > 0` | ~23.268 |
| Grupos de artículos | 43 |
| Fabricantes | 1.072 |
| Tamaño máximo de página del Service Layer | **20 filas** |
| Timeout de sesión | 30 minutos |
| Listas de precio | 1 a 6 (misma estructura) |
| Moneda en precios | `BS` (mapear a `BOB`) |
| Almacén con stock visible | `101-1001` (TIENDA 1); `01` suele estar en 0 |

Otros hallazgos:

- Muchos artículos tienen `(NO USAR)` en el nombre y `Valid = tNO`; hay que
  excluirlos.
- Hay artículos de servicio (`ItemType` distinto de `itItems`) y artículos con
  precio 0; no deben entrar al catálogo.
- El campo `Picture` existe, pero no se ha definido si contiene una imagen útil;
  para WhatsApp conviene una URL pública (CDN/PIM) antes que base64.
- `ForeignName` suele tener el nombre en otro idioma y comillas; sirve como
  descripción secundaria.
- `U_FAMILIA`, `U_LINEA`, `U_SC_Sinonimo` son buenos para sinónimos y filtros.
- `UpdateDate` / `UpdateTime` permiten sincronización incremental.

**Resultado de la primera sync real (QA):** 28.621 artículos con precio válido en
el catálogo local; 21.971 con stock > 0. La búsqueda del bot filtra `stock > 0` y
`price > 0`, así que no muestra artículos agotados.

---

## 2. ¿Consumir el Service Layer directo desde WhatsApp?

**No.** El backend debe actuar como **middleware** entre WhatsApp y SAP:

```text
WhatsApp → backend (catálogo local + búsqueda + carrito)
                ├── sync programado → Service Layer (catálogo)
                └── consultas puntuales → Service Layer (precio/stock al comprar)
```

### Por qué no directo

| Problema | Impacto |
|---|---|
| 20 filas por página | Buscar en 29.731 artículos = ~1.487 llamadas por barrido. |
| Latencia del Service Layer | Cada mensaje esperaría cientos de ms o segundos. |
| Sesión de 30 min | Hay que renovar, serializar logins y manejar 401. |
| Sin búsqueda difusa | SAP filtra por campos exactos; no entiende “algo para la sala”. |
| Sin ranking ni promociones | No hay relevancia, stock visible ni curaduría. |
| Carga sobre SAP | Picos de conversaciones castigan el ERP y compiten con ventas. |
| Acoplamiento | Un cambio de SAP rompe la conversación. |

### Lo que sí debe ser en vivo

- **Precio y stock del SKU** al agregar al carrito y al crear el pedido.
- **Creación de pedido/factura/cobro** en SAP.
- **Estado de pedido** si el cliente pregunta.

Todo lo demás (listar, buscar, filtrar, recomendar, mostrar promociones) se
resuelve contra la copia local.

---

## 3. Arquitectura de catálogo recomendada

### Capa 1 — Sincronización (ETL)

Job programado (por ejemplo cada noche, y incremental cada 10–15 min):

1. Login único al Service Layer.
2. Traer grupos y fabricantes (mapas de códigos a nombres).
3. Traer artículos con filtro:
   ```
   Valid eq 'tYES' and SalesItem eq 'tYES' and ItemType eq 'itItems'
   ```
   paginando de 20 en 20 con `$orderby=ItemCode` y `$skip`.
4. Normalizar:
   - `BS` → `BOB`
   - nombres y descripciones sin comillas
   - precio de la lista configurada (`SAP_PRICE_LIST`)
   - stock total y, si se define, stock del almacén de venta
5. Upsert por `sku` en `catalog_items`.
6. Marcar como inactivos los que ya no vengan (sólo en sync completa).
7. Registrar `synced_at`, `sap_updated_at`, errores y duración.

**Incremental:** `UpdateDate gt <última sync>` si el filtro funciona de forma
confiable; si no, full sync nocturna. La sync completa de ~30.000 artículos son
~1.500 requests; a 0,1–0,2 s por request son 3–5 minutos.

### Capa 2 — Búsqueda local

En PostgreSQL:

- full-text en español sobre nombre + descripción + sinónimos,
- `pg_trgm` para errores de tipeo,
- `pgvector` para búsqueda semántica cuando el catálogo y el lenguaje lo justifiquen,
- filtros SQL por categoría, marca, precio, stock y promoción,
- ranking (stock, relevancia, promoción, margen) y límite de 5–8 resultados.

El bot nunca recibe 29.000 artículos: recibe los 5 mejores.

### Capa 3 — Validación en vivo

Al agregar al carrito y al confirmar:

- `GET /Items('SKU')` con `ItemPrices` y `ItemWarehouseInfoCollection`,
- validar precio de la lista y stock del almacén de venta,
- crear `Orders` y leer `DocTotal` (SAP manda),
- si cambió el precio/stock, informar antes de cobrar.

**Implementación actual:** `HybridSap` consulta el Service Layer con caché de
60 s y *single-flight* por SKU; el checkout usa `force_refresh=True`. Con
`SAP_WRITE_ENABLED=false` las escrituras siguen en `MockSap`, así se valida la
lectura en vivo sin crear documentos en QA.

---

## 4. Filtros para no saturar la conversación

El bot debe aplicar, como mínimo:

- `active = true`
- `stock > 0` para mostrar disponibilidad (o mostrar “agotado” sin precio)
- `price > 0`
- excluir nombres con `(NO USAR)`
- excluir grupos internos (servicios, materias primas, reparación)
- límite de resultados por intención (5)
- una sola consulta por mensaje; cachear 30–60 s las búsquedas repetidas

Si el cliente escribe “algo para la sala”, el LLM extrae filtros
(`categoría=DECO`, `precio<300`) y la búsqueda local devuelve candidatos; no se
hace un barrido de SAP.

---

## 5. Promociones

No conviene inferir promociones desde el histórico de facturas. Opciones, en
orden de preferencia:

1. **Lista de precios dedicada** (por ejemplo lista 4 o 5) para el canal online o
   para promociones vigentes. Se sincroniza el precio de esa lista y se muestra
   como “precio promocional” sólo si el negocio lo confirma.
2. **Campo UDF en SAP** (`U_PROMO`, `U_FECHA_PROMO`) que marque el artículo y su
   vigencia. Requiere que el equipo SAP lo mantenga.
3. **Tabla local `promotions`** con SKU, precio promocional, desde/hasta y texto
   de campaña, administrada desde el panel. Es la más flexible para marketing,
   pero duplica el precio: SAP debe seguir siendo la verdad al cobrar.

Regla: la promoción se muestra desde la fuente que el negocio defina, pero el
total del pedido se recalcula con SAP. Si hay conflicto, gana SAP y se avisa al
cliente.

---

## 6. Precio, stock y almacén

Definir con el negocio:

- **Lista de precios** para B2C/online (hoy el scaffold usa `SAP_PRICE_LIST=1`).
- **Almacén de venta** para el ecommerce. En QA, `101-1001` (TIENDA 1) tiene
  stock; `01` suele estar en 0. Si el ecommerce despacha desde otra bodega,
  cambiar `SAP_WAREHOUSE`.
- **Stock comprometido**: el adaptador calcula `InStock - Committed` del almacén
  configurado; si el campo `Available` viene informado, lo usa.
- **Sobreventa**: validar stock otra vez al crear el pedido; si SAP rechaza,
  ofrecer alternativas.
- **Impuestos**: no calcularlos a mano; se leen del `DocTotal` de SAP.

---

## 7. Imágenes y contenido

WhatsApp necesita imágenes públicas. Opciones:

- `Picture` de SAP si expone una URL o un binario convertible,
- un CDN/PIM con `U_ImgURL` o un campo equivalente,
- una tabla local `catalog_media` (SKU → URL) administrada por marketing.

El nombre de SAP suele ser técnico (“MACETA ELEGANCE CUADR 02…”). Para vender,
conviene una descripción comercial corta, atributos (medidas, color, material) y
sinónimos. Eso se puede editar en el panel sin tocar SAP.

---

## 8. Sincronización inicial: cómo ejecutarla

```powershell
# Catálogo local en SQLite (pruebas)
$env:DATABASE_URL = "sqlite+aiosqlite:///./dev.db"
python -m scripts.sync_catalog --limit 100

# Catálogo completo (Postgres en Docker o local)
python -m scripts.sync_catalog

# Desactivar los que ya no existen en SAP (sólo sync completa)
python -m scripts.sync_catalog --deactivate-missing
```

El script:

- lee grupos y fabricantes,
- pagina artículos con el filtro de vendibles,
- hace upsert por SKU,
- guarda `synced_at` y `sap_updated_at`,
- omite artículos sin precio o sin nombre.

Para producción: programarlo con cron/Task Scheduler o un job de Arq, y
monitorear duración, errores y cantidad sincronizada.

---

## 9. Estimación de carga

| Operación | Frecuencia | Costo |
|---|---|---|
| Sync completa | 1/día | ~1.500 requests, 3–5 min |
| Sync incremental | cada 10–15 min | decenas de requests |
| Búsqueda de catálogo | por mensaje | consulta local (ms) |
| Validación de SKU | al agregar/checkout | 1 request por SKU |
| Crear pedido | por checkout | 1 request |
| Factura + cobro | por pago | 2 requests |

Con esto, una conversación normal hace **0 requests a SAP** hasta que el cliente
agrega al carrito; el resto es base local.

---

## 9.1 Precios especiales, descuentos y stock por tienda

### Stock

Se leen de `Items('SKU') → ItemWarehouseInfoCollection` para:

| Tienda | Almacén |
|---|---|
| Tienda 1 | `101-1001` |
| Tienda 2 | `102-1001` |
| Tienda 3 | `103-1001` |

El stock disponible se calcula como `InStock - Committed` (o `Available` si viene
informado). El carrito elige una tienda con stock suficiente; el cliente puede
pedir otra explícitamente.

### Precios y descuentos

Fuente: **`SpecialPrices`** (no `DiscountGroups`, que no está expuesto, ni
`EnhancedDiscountGroups`, que está vacío en QA).

Datos encontrados:

- 83.180 registros de precio especial.
- 47.835 con `CardCode='*1'` (todos los clientes).
- 56.497 con lista de precios 1.
- Cada registro tiene `SpecialPriceDataAreas` con `DateFrom`, `Dateto`,
  `SpecialPrice`, `Discount`, `PriceListNo` y, opcionalmente,
  `SpecialPriceQuantityAreas`.
- Los escalones por cantidad tienen `Quantity`, `SpecialPrice` y `Discountin`.
- Muchos períodos son históricos (2024–2025); la consulta filtra por fecha al
  calcular la oferta.

Cálculo implementado:

1. Se toma el período vigente (`DateFrom <= hoy <= Dateto`, o sin fecha final).
2. Si hay varios, el de `DateFrom` más reciente.
3. Dentro del período, se toma el escalón con la `Quantity` más alta que no
   supere la cantidad pedida.
4. Si no hay escalón, se usa el `SpecialPrice` del período; si no hay período,
   el precio de lista.
5. El descuento se calcula contra el precio de lista.

La ficha consulta **por SKU** (`SpecialPrices?$filter=ItemCode eq '...'`) con caché
de 300 s. Para que el agente pueda **listar promociones** sin recorrer 83k
registros por mensaje, `scripts/sync_promotions.py` mantiene una tabla local
`product_promotions` con períodos y escalones vigentes/futuros. La última sync
dejó 41.966 filas, de las cuales 4.325 tienen descuento real.

**Ejemplo real QA:** `DCHDCRC200193` tiene precio de lista Bs 2.590 y un período
del 09/12/2025 al 31/12/2026 con precio Bs 1.270 (50,97% de descuento). El bot lo
muestra y lo aplica al carrito; el stock en ese momento era 1 en Tienda 1 y 0 en
las otras dos.

### Pendiente de confirmar con el negocio

- Si `Quantity` es un mínimo (“desde 3 unidades”) o una cantidad exacta.
- Si el `SpecialPrice` es precio unitario o total del escalón.
- Si los precios son brutos (la lista 1 tiene `IsGrossPrice=tYES`).
- Si hay precios por tienda (`U_CXS_WHSPRICE` está vacío hoy).
- Si los descuentos aplican a `*1` o a grupos específicos de clientes.

Mientras no se confirme, el agente muestra el precio calculado y aclara que el
total final se valida en SAP al crear el pedido.

## 10. Decisiones pendientes con el negocio
1. ¿Lista de precios B2C/online? (hoy 1)
2. ¿Almacén de despacho del ecommerce? (hoy `101-1001`)
3. ¿Cómo se marcan las promociones: lista, UDF o tabla local?
4. ¿Se muestran artículos sin stock o sólo disponibles?
5. ¿Qué categorías/grupos se excluyen (servicios, uso interno, reparación)?
6. ¿Fuente de imágenes y descripciones comerciales?
7. ¿Se sincroniza todo el catálogo o sólo las categorías de venta online?
