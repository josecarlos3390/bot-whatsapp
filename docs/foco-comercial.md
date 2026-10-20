# Foco comercial: productos, precios, descuentos y cliente

**Decisión:** facturación y pagos quedan al final. Primero precio correcto,
promociones, historial y análisis del cliente.

**Alcance actual:** una sola lista de precio para B2C (`SAP_PRICE_LIST=1`). No se
construye multi-lista todavía; el diseño debe permitirlo después.

**Implementado en este foco:**
- Búsqueda devuelve `promo_price`, `promo_discount_percent`, `promo_valid_to`
  y `quantity_tiers`.
- `get_product` devuelve todos los escalones vigentes (`tiers`).
- `customer_analysis` (RFM, ticket promedio, segmento) y herramienta
  `get_customer_analysis`.
- `product_sales_stats` + `sync_sales_stats.py` + `get_best_sellers`.
- Resolvedor único de precio `app/services/pricing.py`: SAP primero y fallback
  local con promociones/escalones; checkout no acepta fallback.
- Base de conocimiento en `knowledge/` para envíos, garantías y tiendas.

## 1. Estado actual

| Tema | Hoy | Falta |
|---|---|---|
| Productos | Catálogo local 28.621, búsqueda con filtros, stock por tienda | Imágenes, normalización de marca/categoría, búsqueda full-text |
| Listas de precio | Solo `SAP_PRICE_LIST=1` | Varias listas, precio por cliente, vigencia |
| Descuentos | `SpecialPrices` por período/cantidad | Semántica confirmada, escalones activos, mostrarlos mejor |
| Búsqueda | Devuelve precio base | No muestra promo/descuento en el resultado |
| Historial | `purchase_history` por contacto, evento de factura | Stats globales, recompra, best sellers |
| Cliente | Perfil, hechos, resumen, historial | RFM, segmentos, ticket promedio, categorías, churn |
| Facturación/pagos | Mock | Congelado |

## 2. Orden recomendado

### Fase 1 — Verdad de precio

1. Confirmar cuántas listas de precio existen y cuál usa B2C.
2. Modelo:
   - `PriceList` (`ListNum`, nombre, moneda, bruto/neto, vigencia).
   - `ItemPrice` (`SKU`, `ListNum`, precio, moneda).
   - `Contact.price_list_num`.
3. Sync de `PriceLists`/`ItemPrices` (full o delta).
4. `get_offer(sku, quantity, price_list)` y carrito/pedido usan la lista del cliente.
5. `search_products` devuelve precio de la lista correcta.

**Aceptación:** el mismo SKU muestra el precio correcto para cada lista y el
descuento se calcula sobre esa lista.

**Ahora:** una sola lista. No crear tablas `PriceList`/`ItemPrice` hasta que
exista la segunda lista; sí dejar el parámetro `price_list` en el adaptador y
`Contact.price_list_num` cuando se implemente. La lista actual es
`SAP_PRICE_LIST=1`.

### Fase 2 — Descuentos por período y cantidad

1. Confirmar:
   - ¿`Quantity` es “desde X” o cantidad exacta?
   - ¿`SpecialPrice` es unitario o total?
   - ¿Aplica a todos los clientes (`*1`) o por cliente?
   - ¿Por tienda o compañía?
2. `list_promotions` y `get_product` devuelven:
   - precio normal,
   - precio con descuento,
   - vigencia,
   - escalones por cantidad.
3. `search_products` muestra promo y escalones si existen; si no, precio normal.
4. Si no hay promo, fallback a alternativas y precio regular.
5. `get_best_sellers` usa `product_sales_stats` reales.
6. Tests con períodos activos, vencidos y escalones.

### Fase 3 — Historial y análisis del cliente

1. Historial:
   - compras, ticket promedio, última compra,
   - categorías top, productos recomprables,
   - frecuencia y días sin comprar.
2. `customer_analysis`:
   - **R**ecencia, **F**recuencia, **M**onetary,
   - ticket promedio,
   - segmento: nuevo, activo, recurrente, alto valor, en riesgo, inactivo.
3. `product_sales_stats`:
   - unidades/ingresos 30/90 días,
   - margen,
   - best sellers por categoría.
4. Recomendaciones:
   - recompra,
   - cross-sell por categoría,
   - win-back.
5. Sin reseñas inventadas: solo compradores verificados.

### Fase 4 — Contenido y búsqueda

- Imágenes y links para catálogo nativo.
- Normalizar marcas/categorías.
- Full-text/trigram; RAG semántico solo si hace falta.

### Fase 5 — Facturación y pagos

Recién después de que precio, promo, historial y cliente estén estables.

## 3. Preguntas que necesito

1. ¿Cuántas listas de precio hay? ¿B2C usa la 1?
2. ¿El cliente (`BusinessPartner`) tiene `PriceListNum` asignado?
3. ¿Precios brutos o netos? ¿`IsGrossPrice`?
4. ¿Escalón por cantidad es “desde X” o exacto? ¿Precio unitario o total?
5. ¿Descuentos `*1` aplican a todos? ¿Por tienda o compañía?
6. ¿“Más vendido” por unidades, ingresos o margen? ¿30/90 días?
7. ¿Segmentos por umbrales de ticket/frecuencia?

## 4. Primer sprint sugerido

Si B2C usa solo la lista 1:

- Enriquecer búsqueda con promo/precio final.
- Añadir `customer_analysis` (RFM) al perfil.
- `product_sales_stats` desde facturas.
- Tests y documentación.

Si hay varias listas:

- Empezar por `PriceList`/`ItemPrice` y asignación al cliente.
- Luego promo y análisis.

## 5. No hacer todavía

- No tocar facturación/pagos.
- No agregar RAG para precios/stock.
- No inventar “más vendido” sin stats.
- No prometer descuentos fuera de SAP.
