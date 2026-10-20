# Fallback comercial y feedback del cliente

> **Estado:** fallback sin descuento y captura de feedback implementados.
> “Más vendidos” requiere correr `sync_sales_stats`.

## 0. Implementado

- `customer_feedback` (tipo, rating, comentario, pedido, SKU).
- `feedback_requests`: una encuesta post-entrega por pedido, con estado
  `pending → asked → answered/skipped`.
- `record_feedback`, `skip_feedback` y `get_feedback_summary`.
- La encuesta se agenda `FEEDBACK_DELAY_DAYS` días después del pago.
- Prompt: preguntar una sola vez cuando la memoria indica encuesta pendiente.
- Reclamos con `needs_attention` para derivar a humano.
- Dashboard API de feedback (`/admin/feedback/*`).
- Marcación manual de entrega (`POST /admin/orders/{number}/delivered`).
- Envío saliente opcional con plantilla aprobada
  (`FEEDBACK_OUTBOUND_ENABLED=true`) y job horario.
- La encuesta por defecto es de **atención** (`service`), no de entrega:
  el bot no inventa estados logísticos. La de entrega se crea recién con un
  evento/endpoint de entrega.
- 59 tests.

## 0.1 Dashboard de feedback

Con `X-Admin-Token`:

```http
GET /admin/feedback/summary
GET /admin/feedback/pending
GET /admin/feedback/complaints
POST /admin/feedback/{id}/acknowledge
POST /admin/orders/{number}/delivered
```

`delivered` marca `orders.delivered_at` y adelanta la encuesta a “ahora”. Sirve
para probar el ciclo sin integración de logística.

## 0.2 Plantilla saliente

La encuesta saliente después de 24 h requiere una plantilla aprobada. Ver
[plantillas-whatsapp.md](plantillas-whatsapp.md).

## 1. Si no hay descuento

Nunca responder solo “no hay”. El orden debe ser:

1. Buscar sin `only_discount`.
2. Mantener categoría/marca; ampliar precio si hace falta.
3. Ofrecer 3–5 alternativas con precio normal.
4. Explicar que no hay promo vigente, sin inventar una.
5. Si hay datos, ordenar por **más vendidos** o mejor rotación.
6. Cerrar con “¿te muestro estas o querés otra marca?”.

El backend ya devuelve `fallback_without_discount=true` cuando no encuentra con
descuento, para que el agente no invente.

### “Más vendidos”

No se puede afirmar sin datos. Hay que construir `product_sales_stats` con:

- unidades vendidas 30/90 días,
- ingresos,
- margen,
- rotación,
- stock.

Mientras no exista, ofrecer “alternativas disponibles” o “recomendados”, no
“los más vendidos”.

### Reseñas

No inventar testimonios. Solo usar:

- reseñas reales de compradores verificados,
- promedio y cantidad,
- comentarios moderados.

Si no hay reseñas, usar especificaciones y beneficio (“2 plazas, 140x190,
espuma semipedic”), no una reseña falsa.

---

## 2. Feedback: cuándo preguntar

No preguntar al inicio ni en cada conversación. Preguntar **después de un evento**:

| Momento | Pregunta | Tipo |
|---|---|---|
| Después del pago | “¿Cómo fue tu experiencia de compra?” | CSAT |
| Después de la entrega | “¿Llegó en el tiempo esperado?” | Delivery |
| Después de usar el producto | “¿Cumplió lo que esperabas?” | Product |
| Al cerrar una atención | “¿Cómo calificás la atención?” | Service |
| Cliente frecuente | “¿Qué podríamos mejorar?” | Open |

Reglas:

- Una pregunta a la vez.
- Opcional y explícito: “Si tenés 10 segundos… si no, no hay problema”.
- No bloquear la venta ni el soporte.
- No preguntar dos veces lo mismo por pedido.
- Máximo una encuesta cada 30 días.
- No usar las respuestas negativas para castigar al cliente.
- Ofrecer opción anónima si aplica.

---

## 3. Ejemplos

> “Antes de cerrar: ¿cómo calificás la atención de 1 a 5? Si no querés responder,
> seguimos nomás.”

> “¿El colchón cumplió lo que esperabas? 👍 Sí / 😐 Más o menos / 👎 No.”

> “¿La entrega llegó en el tiempo que te prometimos?”

> “¿Qué podríamos mejorar? Podés escribir una idea o decir ‘nada’.”

Si la respuesta es negativa:

- agradecer,
- ofrecer solución o derivar a humano,
- registrar el caso,
- no defenderse.

---

## 4. Modelo de datos propuesto

```text
customer_feedback
  id, contact_id, order_id, type, rating, comment,
  sku, channel, consent, created_at

feedback_requests
  id, order_id, type, sent_at, responded_at, status
  unique(order_id, type)

product_sales_stats
  sku, units_30d, revenue_30d, margin_pct, rotation_score, updated_at

review_summary
  sku, avg_rating, review_count, last_review_at
```

`feedback_requests` evita preguntar dos veces y permite medir respuesta.

---

## 5. Herramientas

```text
record_feedback(type, rating?, comment?, order_number?, sku?, consent=true)
get_feedback_summary()
get_best_sellers(category?, brand?, limit=5)
```

- `record_feedback` guarda la respuesta y, si es negativa, puede abrir handoff.
- `get_feedback_summary` alimenta reseñas y métricas.
- `get_best_sellers` usa `product_sales_stats`.

---

## 6. Encuestas salientes

Después de la ventana de 24 h, WhatsApp exige **plantilla aprobada** para iniciar
la conversación. Por eso:

- pedir opt-in al comprar,
- usar plantilla `encuesta_compra` o `encuesta_entrega`,
- enviar una sola vez,
- respetar opt-out,
- no mandar encuestas a quien no aceptó.

---

## 7. Qué implementar primero

1. Fallback sin descuento (ya implementado).
2. `customer_feedback` + `record_feedback` + una encuesta post-compra.
3. `product_sales_stats` para “más vendidos”.
4. Reseñas agregadas y moderación.
5. Dashboard de CSAT/NPS y cierres de mejora.

La regla de oro: **preguntar poco, escuchar bien y cerrar el ciclo**. Si el
cliente da feedback y nadie hace nada, es peor que no preguntar.
