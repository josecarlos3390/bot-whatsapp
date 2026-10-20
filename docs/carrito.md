# Carrito editable y carrito nativo

## Carrito del bot

El cliente puede:

- agregar,
- quitar un producto,
- cambiar cantidad,
- vaciar el carrito,
- ver el resumen,
- confirmar el pedido.

Herramientas:

| Herramienta | Acción |
|---|---|
| `add_to_cart` | Agrega unidades |
| `remove_from_cart` | Quita un SKU |
| `update_cart_quantity` | Cambia cantidad; 0 quita |
| `clear_cart` | Vacía todo |
| `view_cart` | Muestra el resumen |

También funciona por texto:

> “vacía mi carrito”
> “quita la mesa”
> “pon 2 colchones”

El bot confirma con el resultado real de la herramienta; no inventa que lo hizo.

## Carrito nativo de WhatsApp

El carrito nativo vive **del lado del cliente**, en la interfaz de WhatsApp.
El servidor no puede:

- borrarlo,
- editarlo,
- leerlo antes de que el cliente envíe el pedido.

Cuando llega un pedido nativo:

1. el webhook trae `order.product_items`,
2. el bot **reemplaza** el carrito del bot con esos ítems,
3. valida precio y stock,
4. responde con el resumen.

Eso queda preparado con:

```text
sync_mode = replace_on_native_order
server_side_cart = false
```

## Estado de integración

```http
GET /admin/commerce/status
```

Devuelve:

```json
{
  "native_catalog_enabled": false,
  "native_cart_enabled": false,
  "ready": false,
  "cart_ready": false,
  "server_side_cart": false,
  "sync_mode": "replace_on_native_order"
}
```

## Cuándo activarlo

- número de producción,
- Commerce Manager,
- catálogo aprobado,
- productos con imagen y precio,
- `WA_NATIVE_CATALOG_ENABLED=true`,
- `WA_NATIVE_CART_ENABLED=true`.

Mientras esté apagado, se usa el carrito propio del bot.
