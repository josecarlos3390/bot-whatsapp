# Catálogo nativo de WhatsApp y carrito de Meta

## Qué es cada cosa

| Pieza | Qué hace | Dónde se configura |
|---|---|---|
| **Catálogo de Meta** | El cliente ve productos dentro de WhatsApp | Commerce Manager |
| **Feed** | Lista de productos que Meta lee cada día | Nuestro bot (URL con token) |
| **Producto nativo** | Mensaje con foto, precio y botón "Agregar" | Bot (requiere catálogo) |
| **Carrito nativo** | El cliente arma el pedido dentro de WhatsApp | Bot + catálogo |
| **Pedido nativo** | Llega como mensaje `order` con los SKU | Bot (ya lo procesa) |

## Lo que ya está listo en el bot

| Pieza | Estado |
|---|---|
| Feed CSV del catálogo | ✅ `/feeds/catalog/{token}.csv` |
| Token del feed | ✅ `META_CATALOG_FEED_TOKEN` en `.env` |
| Lectura de pedidos nativos (`order`) | ✅ `services/native_commerce.py` |
| Envío de mensajes de producto | ✅ `whatsapp.py` (`product`, `product_list`) |
| Interruptores | ⏸ `WA_NATIVE_CATALOG_ENABLED`, `WA_NATIVE_CART_ENABLED` |

El feed incluye **3.644 productos** (solo activos, con stock y con foto).

Columnas: `id`, `title`, `description`, `availability`, `condition`, `price`,
`link`, `image_link`, `brand`, `category`.

`id` es el **SKU**: es lo que vuelve en el pedido nativo.

## Lo que falta para activarlo

### 1. Crear el catálogo

[Commerce Manager](https://business.facebook.com/commerce_manager/) → **Crear
catálogo** → tipo **Comercio electrónico**.

Anotar el **ID del catálogo** y el **ID de la cuenta comercial**.

### 2. Cargar el feed

En el catálogo → **Fuentes de datos** → **Agregar productos** → **Fuente por
URL**:

```
https://{dominio}/feeds/catalog/{META_CATALOG_FEED_TOKEN}.csv
```

Programación: **cada 6 horas**.

Meta revisa la fuente y puede tardar horas en aprobar los productos.

### 3. Conectar el catálogo a WhatsApp

WhatsApp Manager → **Herramientas de la cuenta** → **Catálogo** → vincular el
catálogo del paso 1.

Sin este paso, el número no puede mandar mensajes de producto.

### 4. Configurar el `.env`

```env
WA_CATALOG_ID=...
WA_COMMERCE_ACCOUNT_ID=...
META_CATALOG_LINK_BASE=https://roho.com.bo/producto
WA_NATIVE_CATALOG_ENABLED=true
WA_NATIVE_CART_ENABLED=true
```

`META_CATALOG_LINK_BASE` arma el link de cada producto:
`https://roho.com.bo/producto/{sku}`.

⚠️ **Depende de que el ecommerce esté público.** Hoy `roho.com.bo` está en
mantenimiento y `rodabo.myvtex.com` redirige al login de administración: Meta
necesita links que abran sin sesión.

### 5. Probar

1. El bot manda un producto nativo.
2. El cliente toca **Agregar** y **Ver carrito**.
3. Al confirmar, llega un mensaje `order`.
4. El bot lo convierte en su carrito y responde con el total.

## Limitaciones que hay que saber

| Limitación | Consecuencia |
|---|---|
| El carrito vive en WhatsApp | El bot no puede borrar ni editar líneas del carrito nativo |
| El cliente puede cambiar precios | Hay que **validar contra el catálogo** al recibir el pedido |
| Solo productos del catálogo | Un SKU sin producto aprobado no aparece |
| El feed tarda en procesarse | Los cambios de precio no son inmediatos |
| `link` obligatorio | Sin ecommerce público, Meta puede rechazar la fuente |
| Catálogo aprobado | Meta revisa productos (imágenes, títulos, precios) |

## Cómo convive con el carrito propio

```
Cliente escribe "quiero un taladro"
        ↓
Bot busca en SU catálogo (28.677 productos)
        ↓
Muestra tarjetas propias (texto + listas)
        ↓
¿Catálogo nativo activo?
   sí → además manda el producto nativo
   no → solo el texto
```

**Los dos carritos pueden coexistir:** el nativo para quien lo use, el propio
como respaldo. Al recibir un `order`, el bot lo pasa a su carrito y sigue el
flujo normal (link de pago).

## Riesgo si se activa sin probar

| Caso | Qué pasa |
|---|---|
| SKU del pedido no está en el catálogo local | Se ignora y se avisa |
| Precio nativo distinto al del bot | Se valida contra el catálogo |
| Catálogo desactualizado | Se ofrece lo que ya no hay |

## Orden recomendado

```
1. Publicar la app y el número (sin catálogo nativo)
2. Probar el flujo completo con testers
3. Crear el catálogo y cargar el feed
4. Vincular el catálogo a WhatsApp
5. Activar WA_NATIVE_CATALOG_ENABLED
6. Activar WA_NATIVE_CART_ENABLED
```

**El catálogo nativo es un extra, no un requisito.** El bot funciona completo
sin él.
