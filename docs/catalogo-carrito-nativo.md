# Catálogo y carrito nativo: adaptación

**Estado:** preparado, apagado por defecto. El bot sigue usando su catálogo y
carrito propios hasta que Meta habilite el catálogo del número de producción.

## 1. Qué ya está listo

| Pieza | Implementación |
|---|---|
| Flags | `WA_NATIVE_CATALOG_ENABLED`, `WA_NATIVE_CART_ENABLED` |
| IDs | `WA_CATALOG_ID`, `WA_COMMERCE_ACCOUNT_ID` |
| Mensajes | `catalog`, `product`, `product_list` en `whatsapp.py` |
| Pedido nativo | `extract_order`, `parse_order`, `add_order_to_cart` |
| Carrito | Convierte el pedido nativo en `CartItem` con precio/stock SAP |
| Catálogo | `scripts/export_meta_catalog.py` genera CSV para Commerce Manager |
| Filtros | `search_products` acepta categoría, marca, precio y descuento |
| Catálogo filtrado | `show_catalog` arma `product_list`/`product` con los resultados |
| Estado | `GET /admin/commerce/status` |
| Fallback | Con flags apagados, todo sigue igual que hoy |

## 2. Flujo cuando se active

```text
Cliente: "busco colchones en descuento de la marca X hasta Bs 2.000"
        ↓
Bot entiende filtros: categoría, marca, precio, descuento
        ↓
search_items filtra el catálogo local
        ↓
show_catalog arma un product_list con los resultados
        ↓
Cliente toca un producto y lo agrega al carrito nativo
        ↓
Webhook type=order
        ↓
Bot convierte product_items en carrito
        ↓
Resumen y checkout/QR
```

### Catálogo dinámico: lo importante

- `catalog_message` muestra **el catálogo completo**; Meta no permite pasarle
  filtros de marca/precio/descuento.
- Para mostrar solo lo que el cliente pidió se usa **`product_list`**: una lista
  de productos seleccionados por el bot, con secciones.
- Si hay un solo producto, se puede enviar **`product`**.
- Si hay muchos, mostrar 5–8 y ofrecer “ver más” o “catálogo completo”. No
  mandar 30 productos de golpe.
- El filtro se hace en el backend (`category`, `brand`, `min_price`, `max_price`,
  `only_discount`) y luego se arma la lista.
- Si el cliente refina (“más baratos”, “otra marca”), se vuelve a filtrar y se
  envía una nueva `product_list`.

Con el número de prueba no se puede usar `product_list` nativo; el bot responde
con texto y los mismos filtros. Cuando haya acceso, `show_catalog` envía la lista
nativa.

## 3. Activación

### 3.1 Requisitos Meta

- Número de producción en Cloud API.
- Catálogo aprobado en Commerce Manager.
- Catálogo conectado a la WABA.
- `is_catalog_visible` e `is_cart_enabled` activos.

### 3.2 Variables

```env
WA_NATIVE_CATALOG_ENABLED=true
WA_NATIVE_CART_ENABLED=true
WA_CATALOG_ID=<catalog_id>
WA_COMMERCE_ACCOUNT_ID=<commerce_account_id>
META_CATALOG_LINK_BASE=https://tu-tienda.com/producto
META_CATALOG_PLACEHOLDER_IMAGE=https://.../placeholder.jpg
```

### 3.3 Exportar catálogo

```powershell
python -m scripts.export_meta_catalog --out meta_catalog.csv
```

Subí el CSV a Commerce Manager o usá su feed programado.

Campos:

- `id` = SKU (`retailer_id`).
- `title`, `description`, `price`, `availability`.
- `link` = `META_CATALOG_LINK_BASE/SKU`.
- `image_link` = imagen del producto o placeholder.
- `brand`, `category`.

Sin imagen o sin link, Meta puede rechazar el feed.

### 3.4 Probar

```http
GET /admin/commerce/status
```

Debe devolver `ready: true` y `cart_ready: true`.

Después:

1. Enviar “ver catálogo” → debe salir el catálogo nativo.
2. Agregar productos y enviar el pedido.
3. Verificar que el webhook `order` cree el carrito.
4. Confirmar checkout/QR.

## 4. Consideraciones

- **Precio/stock:** el catálogo de Meta es una foto. El checkout siempre valida
  contra SAP; si cambió el precio, se muestra el nuevo.
- **SKU:** `product_retailer_id` debe ser exactamente el `ItemCode`.
- **Imágenes:** si el catálogo local no tiene `image_url`, usar placeholder solo
  para pruebas; producción necesita imágenes reales.
- **Link:** Meta exige una URL de producto válida.
- **Pedido nativo:** puede traer `item_price`; no confiar en él para cobrar.
- **Catálogo propio:** sigue disponible como fallback si el nativo falla.

## 5. Archivos

- `app/services/native_commerce.py`
- `app/whatsapp.py`
- `app/services/ingest.py`
- `app/api.py` (`/admin/commerce/status`)
- `scripts/export_meta_catalog.py`
- `tests/test_native_commerce.py`
