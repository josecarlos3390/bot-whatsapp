# Evolución del agente: memoria, historial y recomendaciones

**Estado:** 19-oct-2026. El bot ya vende, sugiere promociones y recuerda el hilo
reciente. La **Fase A** (perfil, hechos y resumen) ya está implementada; falta
historial de compras y recomendaciones basadas en él.

---

## 0. Fase A implementada

| Pieza | Implementación |
|---|---|
| Perfil | `customer_profiles` (ciudad, tienda, cumpleaños, preferencias, consentimiento) |
| Hechos | `customer_facts` (clave/valor, consentimiento obligatorio) |
| Resumen | `conversation_summaries`, generado en segundo plano cada ~8 mensajes |
| Herramientas | `get_customer_profile`, `remember_customer_fact` |
| Contexto | El prompt recibe perfil + hechos + resumen, además de los últimos 10 mensajes |
| Privacidad | No se guardan carnet/tarjeta/contraseñas; se exige consentimiento |

El resumen se genera con DeepSeek en modo no-thinking, fuera del camino crítico
del mensaje. Si falla, el bot sigue respondiendo.

La **Fase B** (historial de compras SAP y recomendaciones) ya está implementada
para clientes con `sap_card_code`.

### Base de datos y trabajos

- Migración inicial de **Alembic** (`alembic/versions/`) probada en SQLite y
  **PostgreSQL 18**: `alembic upgrade head` y `alembic check` sin diferencias.
- Local sigue en SQLite; producción debe usar PostgreSQL con
  `AUTO_CREATE_DB=false`.
- El resumen se encola como job de **Arq** si `QUEUE_ENABLED=true`; si no, corre
  en segundo plano del proceso para desarrollo.
- La caché de precio/stock sigue en memoria por proceso; moverla a Redis es la
  siguiente mejora de escalabilidad.

---

## 1. Qué hace hoy

| Capacidad | Estado |
|---|---|
| Conversación | Guarda mensajes y usa los últimos 10 como contexto |
| Memoria de largo plazo | **Sí, Fase A**: resumen + hechos + perfil |
| Promociones | `product_promotions` + `list_promotions` |
| Precio/stock por SKU | SAP en vivo, caché 60 s, stock por 3 tiendas |
| Carrito/pedido | Sí; pedido SAP sigue mock |
| Historial de compras | **Sí, Fase B**: `purchase_history` + `purchase_history_lines` desde facturas SAP |
| Identificación | Carnet/NIT → `FederalTaxID` en SAP; se confirma nombre y se vincula `CardCode` |
| Recomendaciones | **Sí**: `recommend_for_customer` usa categorías compradas + promociones |
| Análisis de cliente | **Sí**: `customer_analysis` con RFM, ticket promedio y segmento |
| Más vendidos | **Sí**: `product_sales_stats` + `get_best_sellers` (requiere sync de facturas) |
| Feedback | **Sí**: `customer_feedback`, `record_feedback`, resumen y reclamos |
| Actualización de datos | Cron en el worker (promos cada 6 h, catálogo 03:20) |

---

## 2. Actualización periódica

`app/worker.py` ya define cron jobs:

```python
cron(job_sync_promotions, hour={0, 6, 12, 18}, minute=10)
cron(job_sync_catalog, hour=3, minute=20)
```

- **Promociones**: cada 6 h (la sync completa tarda varios minutos).
- **Catálogo**: 03:20.
- **Compras**: 04:10 (facturas por cliente con `sap_card_code`).
- Requiere `QUEUE_ENABLED=true` y el worker Arq corriendo.
- Para producción conviene **incremental** por `UpdateDate` y promociones cada
  15–30 min; hoy la full sync es la única implementada.

Sin worker, se ejecuta a mano:

```powershell
python -m scripts.sync_catalog
python -m scripts.sync_promotions
```

---

## 3. “Top” de productos con descuento

Hoy `list_promotions`:

- filtra vigencia y stock,
- exige precio base mínimo (20 Bs por defecto),
- ordena por porcentaje de descuento,
- diversifica categorías,
- devuelve hasta 5.

No usa rotación, margen ni historial. Para un “top comercial” conviene un score:

```text
score = 0.35 * descuento_pct
      + 0.20 * ahorro_absoluto
      + 0.20 * rotacion_30d
      + 0.15 * margen
      + 0.10 * stock_disponible
```

Con filtros:

- stock > 0 en la tienda,
- precio dentro del presupuesto,
- categoría relevante,
- excluir productos de bajo valor percibido,
- no repetir categoría,
- priorizar recompra o complemento.

**Datos necesarios:** ventas por SKU (unidades/ingresos 30–90 días), costo/margen,
rotación y stock por tienda. Se obtienen de facturas/pedidos de SAP y se guardan
en `product_sales_stats`.

---

## 4. Memoria de conversación

### Hoy

- `messages` guarda todo.
- El prompt recibe los últimos 10 mensajes.
- Al reabrir el chat, el historial sigue ahí, pero el LLM no “recuerda”hechos
  viejos ni un resumen.

### Propuesta

1. **Resumen incremental** (`conversation_summaries`):
   - cada 10–15 mensajes, un job resume: necesidad, objeciones, productos vistos,
     tienda, presupuesto, estado.
   - el prompt incluye resumen + últimos 6 mensajes.
2. **Hechos del cliente** (`customer_facts`):
   - `prefiere_deco`, `tiene_mascota`, `presupuesto_200`, `talla`, `color`,
   - `no_le_gusta_presion`, `compro_para_regalo`.
   - Cada hecho con `source`, `confidence`, `updated_at`.
3. **No guardar** datos sensibles innecesarios (salud, religión, política).
4. **Consentimiento** y opción de borrado.

---

## 5. Historial de compras

### Fuente de verdad

SAP: `BusinessPartners` + `Invoices`/`Orders`.

Flujo:

1. Identificar al cliente por teléfono (`Phone1`) o `CardCode`.
2. Consultar facturas de los últimos 12–24 meses.
3. Guardar en local `purchase_history`:
   - `contact_id`, `sap_doc_entry`, `doc_type`, `doc_date`, `total`,
   - líneas: `sku`, `category`, `quantity`, `amount`.
4. Calcular:
   - frecuencia, ticket promedio, última compra,
   - categorías top, marcas top,
   - productos recomprables (consumibles),
   - productos complementarios.

### Herramientas nuevas

```text
get_customer_profile()
get_purchase_history(limit=10)
recommend_for_customer(need?, budget?, limit=3)
remember_customer_fact(key, value)
```

El agente puede decir: “La última vez llevaste macetas; tengo el sustrato con
20% y combina con lo que compraste”.

---

## 6. Carnet / identidad

Se puede, pero **no es lo primero** y requiere cuidado:

- El teléfono ya identifica la conversación; el `CardCode` de SAP identifica al
  cliente.
- El carnet boliviano es dato personal sensible: pedirlo en el chat, guardarlo y
  mostrarlo aumenta el riesgo.
- Si se necesita para factura:
  - pedirlo **solo al cerrar la compra**,
  - validar formato,
  - cifrarlo en reposo,
  - no mostrarlo completo en logs ni en el chat,
  - permitir borrarlo.
- En SAP, `FederalTaxID` hoy se usa para RUT (localización chilena). No asumir que
  es el carnet; mapear a un campo/UDF distinto.

**Recomendación:** identificación por teléfono + número de pedido/OTP. Carnet solo
si el negocio lo exige para facturación.

---

## 7. Recomendaciones basadas en compras

Reglas + LLM:

| Tipo | Ejemplo |
|---|---|
| Recompra | “Se te acabó el limpiador; ¿lo repetimos?” |
| Cross-sell | maceta → sustrato, planta → maceta |
| Upsell | 3 unidades → escalón de precio |
| Win-back | “Hace 90 días no compras; tengo 20% en tu categoría” |
| Regalo | presupuesto + ocasión + stock |

El LLM no calcula; recibe del backend:

- perfil resumido,
- categorías top,
- última compra,
- promociones activas,
- stock por tienda.

---

## 8. Interactividad y perfilamiento

Para que pregunte datos sin ser invasivo:

1. **Progresivo**: solo pide lo que necesitas en ese paso.
2. **Una pregunta a la vez**.
3. **Explica el beneficio**: “Para recomendarte mejor, ¿es para interior o exterior?”
4. **No preguntes lo que ya sabes** (nombre, tienda, última compra).
5. **Recompensa**: “Con eso te muestro solo lo que sí te sirve”.
6. **Consentimiento** para guardar preferencias y enviar promociones.
7. **Nunca** pidas carnet/tarjeta al inicio.

Perfil sugerido:

```text
nombre, teléfono, ciudad, tienda habitual, cumpleaños (opcional),
categorías favoritas, presupuesto habitual, opt-in marketing,
documento (solo si factura; cifrado), notas comerciales
```

---

## 9. Modelo de datos propuesto

| Tabla | Campos |
|---|---|
| `customer_profiles` | `contact_id`, `city`, `birthday`, `preferred_store`, `preferences_json`, `consent_at` |
| `customer_facts` | `contact_id`, `key`, `value`, `source`, `confidence`, `updated_at` |
| `conversation_summaries` | `conversation_id`, `summary`, `updated_at` |
| `purchase_history` | `contact_id`, `sap_doc_entry`, `doc_type`, `doc_date`, `total` |
| `purchase_history_lines` | `history_id`, `sku`, `category`, `quantity`, `amount` |
| `product_sales_stats` | `sku`, `units_30d`, `revenue_30d`, `margin_pct`, `rotation_score` |
| `recommendations` | `contact_id`, `sku`, `reason`, `score`, `created_at` |

---

## 10. Roadmap

### Fase A — Memoria básica ✅

- Resumen de conversación cada N mensajes.
- `customer_profiles` + `customer_facts`.
- Herramienta `get_customer_profile`.
- Prompt: usar perfil, no volver a preguntar.

### Fase B — Historial y recomendaciones ✅ (base)

- Sync de facturas/pedidos por `CardCode` (`scripts/sync_purchases.py`).
- `purchase_history` + `get_purchase_history`.
- `recommend_for_customer` por categorías compradas.
- Pendiente: score con rotación/margen y sync incremental programado.

### Fase C — Identidad y segmentos

- Carnet/NIT: **implementado** (`identify_customer` + `link_customer` + redacción).
- Segmentos: nuevo, recurrente, alto valor, inactivo (pendiente).
- Campañas con plantillas aprobadas (pendiente).

### Fase D — Optimización

- Evals con conversaciones reales.
- A/B de prompts.
- Medición de conversión y ticket.
- Job de carrito abandonado.

---

## 11. Qué se necesita

- Worker Arq + Redis en producción (`QUEUE_ENABLED=true`).
- Acceso de lectura a facturas/pedidos de SAP por `CardCode`.
- Definir con el negocio:
  - qué datos se pueden pedir y guardar,
  - política de privacidad y consentimiento,
  - cuánto tiempo se retienen,
  - si el carnet es obligatorio para factura.
- Tablas y migraciones (Alembic) para las nuevas entidades.
- Evaluación con clientes reales antes de activar recomendaciones automáticas.

La personalidad sin memoria es un vendedor que olvida al cliente; la memoria sin
datos es un CRM vacío. La ventaja está en unir conversación, compras y promociones.
