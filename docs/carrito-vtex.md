# Carrito espejo en VTEX

## Qué hace

El bot arma el carrito en su base y **lo replica en un carrito de VTEX**
(`orderForm`). Con ese carrito:

1. El cliente recibe un **link** para revisar y pagar en la tienda.
2. El recordatorio de WhatsApp puede apuntar a **ese mismo link**.
3. Si el cliente paga en VTEX, la venta queda registrada allá (no en el bot).

## Por qué así y no al revés

El carrito del bot sigue siendo el que manda mientras conversa: si VTEX falla,
la venta no se cae. Cuando VTEX responde, se copia. Nunca al revés.

```
Cliente agrega → carrito local (fuente de verdad)
                        ↓
                se copia a VTEX (best effort)
                        ↓
             si hay orderForm → link para pagar
```

## Estado actual

| Pieza | Estado |
|---|---|
| Crear carrito en VTEX | ✅ Implementado |
| Copiar artículos | ✅ Implementado |
| Guardar `orderFormId` y link | ✅ Implementado |
| Botón de pago en el chat | ✅ Implementado |
| Recordatorio con link | ✅ Preparado (plantilla con botón URL) |
| **Credenciales de VTEX** | ❌ **Faltan** |

Sin credenciales el servicio queda **apagado** y el bot sigue funcionando con
su carrito local y el paso a un asesor.

## Lo que hace falta

En `.env`:

```
VTEX_CART_ENABLED=true
VTEX_ACCOUNT=roho
VTEX_ENVIRONMENT=vtexcommercestable
VTEX_APP_KEY=...
VTEX_APP_TOKEN=...
VTEX_SALES_CHANNEL=1
VTEX_CHECKOUT_HOST=https://roho.com.bo
```

| Dato | De dónde sale |
|---|---|
| `VTEX_ACCOUNT` | El nombre de la tienda en VTEX (subdominio) |
| `VTEX_APP_KEY` / `APP_TOKEN` | VTEX → Configuración de la cuenta → Claves de aplicación |
| `VTEX_SALES_CHANNEL` | Canal de ventas (1 = tienda principal, normalmente) |
| `VTEX_CHECKOUT_HOST` | Dominio que ve el cliente (no el de la API) |

## Permisos que necesita la clave

| Recurso | Para qué |
|---|---|
| Checkout (orderForm) | Crear y modificar el carrito |
| Catálogo (lectura) | Validar SKU y disponibilidad |
| Pedidos (lectura) | Ver si el cliente terminó la compra |

## Cómo se prueba

```powershell
# Con credenciales configuradas
.\.venv\Scripts\python.exe -c "from app.services import vtex_cart; print('disponible:', vtex_cart.disponible())"
```

Y en el chat: agregar un producto → el bot debe responder con un botón
**Terminar mi compra** que abre el carrito en VTEX.

## Riesgos a validar antes de producción

| Riesgo | Qué mirar |
|---|---|
| **Precio distinto** | VTEX recalcula promociones y puede mostrar otro total |
| **Stock por sucursal** | El bot elige una sucursal; VTEX usa la suya |
| **Envío** | El costo final lo calcula VTEX en el checkout |
| **Link compartido** | Quien tenga el link puede pagar: es un comprobante temporal |
| **Sesión del cliente** | No requiere registro para pagar; si inicia sesión, se le asocian sus datos |

## Lo que NO resuelve

- **No crea el pedido**: eso lo hace el cliente al pagar en VTEX.
- **No valida el pago**: eso llega por el webhook de VTEX/Cucu, no por acá.
- **No sincroniza al revés**: si el cliente cambia el carrito en VTEX, el bot
  no se entera hasta que vuelva a escribir.
