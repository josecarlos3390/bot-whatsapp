# Pedido al equipo del PaaS: carrito de VTEX

**Para:** equipo que mantiene el integrador PaaS (VTEX).
**De:** equipo del bot de WhatsApp de ROHO Homecenter.
**Fecha:** 3 de noviembre de 2026.

---

## 1. Qué necesitamos y por qué

Hoy el bot arma el carrito **en su propia base** y, cuando el cliente quiere
comprar, lo pasa a un asesor que genera el pedido a mano. Eso tiene dos
problemas:

- El cliente espera a que alguien lo atienda.
- Si abandona, se pierde la venta.

Queremos que el cliente **termine la compra solo**, en VTEX, desde un link.
Para eso el bot necesita crear un carrito en VTEX y copiarle los productos.

## 2. Qué usamos hoy del PaaS

Solo lectura, y funciona bien:

| Ruta | Uso |
|---|---|
| `GET /api/vtex/items/export` | Catálogo |
| `GET /api/vtex/brands` | Marcas |
| `GET /api/vtex/orders` | Consulta de pedidos |
| `GET /api/vtex/customers/...` | Clientes |

## 3. Qué necesitamos agregar

Tres operaciones. Los nombres son una propuesta; nos adaptamos a lo que
ustedes definan, siempre que la semántica sea la misma.

### 3.1 Crear un carrito

```
POST /api/vtex/cart
```

**Request:**

```json
{
  "sales_channel": 1,
  "affiliate_id": null
}
```

**Response 200:**

```json
{
  "order_form_id": "8f3a2b1c9d4e5f6a7b8c9d0e1f2a3b4c",
  "checkout_url": "https://roho.com.bo/checkout/#/orderform/8f3a2b...",
  "items": [],
  "value": 0
}
```

**Notas:**

- El carrito es **anónimo** (no requiere cliente identificado).
- `checkout_url` es el link que le mostramos al cliente. Si prefieren que lo
  armemos nosotros, alcanza con `order_form_id` y el dominio.

### 3.2 Agregar o cambiar productos

```
POST /api/vtex/cart/{order_form_id}/items
```

**Request:**

```json
{
  "items": [
    { "sku": "PTRPARD020198", "quantity": 3, "seller": "1" },
    { "sku": "HRRAELC310100", "quantity": 1, "seller": "1" }
  ]
}
```

**Response 200:**

```json
{
  "order_form_id": "8f3a...",
  "items": [
    { "sku": "PTRPARD020198", "quantity": 3, "price": 419.0, "name": "Impermeabilizante..." }
  ],
  "value": 1257.0,
  "messages": []
}
```

**Comportamiento esperado:**

- Si el SKU ya está en el carrito, **actualiza la cantidad** (no duplica).
- Si la cantidad es 0, se quita.
- Si VTEX rechaza un ítem (sin stock, SKU inexistente), responder `200` con
  ese ítem ausente de `items` y un detalle en `messages`, sin fallar todo.

### 3.3 Consultar el carrito (opcional pero útil)

```
GET /api/vtex/cart/{order_form_id}
```

**Response 200:** mismo formato que 3.2.

Sirve para confirmar que el carrito quedó como el bot cree y para mostrar el
total actualizado antes de mandar el link.

## 4. Errores que necesitamos distinguir

| Situación | HTTP | Cuerpo |
|---|---|---|
| Carrito inexistente o vencido | `404` | `{"error": "order_form_not_found"}` |
| SKU sin stock o inválido | `200` + `messages` | ver 3.2 |
| Falla de VTEX | `502` | `{"error": "vtex_error", "detail": "..."}` |

Con `404` el bot crea un carrito nuevo; con `502` avisa al cliente y sigue
con su carrito local.

## 5. Qué NO necesitamos

| Cosa | Por qué |
|---|---|
| Crear el pedido | Lo hace el cliente al pagar |
| Cobrar | Igual: lo resuelve el checkout de VTEX |
| Datos del cliente | El carrito es anónimo |
| Envío o dirección | Se eligen en el checkout |

## 6. Seguridad

- Se usa la **misma `X-API-Key` y tenant** que el resto de las rutas.
- El `order_form_id` es un identificador largo y aleatorio; no adivinable.
- No guardamos datos de tarjeta ni de pago.

## 7. Preguntas concretas

1. **¿Se puede exponer?** ¿Hay alguna restricción de permisos de VTEX con la
   clave actual de la cuenta?
2. **¿Los nombres de ruta les sirven** o prefieren otros?
3. **`seller`**: ¿siempre `"1"` o depende del canal/sucursal?
4. **Promociones**: ¿el precio del carrito respeta la lista `1` y las
   promociones vigentes? Nuestro bot muestra el precio con descuento y no
   queremos que el cliente vea otro total en el checkout.
5. **Stock**: ¿VTEX valida contra el mismo inventario que usamos hoy
   (`stock_by_store`)?
6. **Vencimiento**: ¿cuánto dura un `orderForm` inactivo? Lo necesitamos para
   saber hasta cuándo sirve el link del recordatorio.
7. **Link del cliente**: ¿el dominio correcto es `roho.com.bo` o hay uno
   específico para checkout?

## 8. Cómo queda del lado del bot

Ya está implementado y **apagado**: cuando las rutas respondan, se activa con:

```
VTEX_CART_ENABLED=true
VTEX_CART_VIA=paas
```

Y el flujo queda:

```
Cliente agrega → carrito del bot → se copia a VTEX → link para pagar
                                      ↓
                        recordatorio con el mismo link
```

## 9. Contacto

Cualquier duda de formato o de casos borde, escribime y lo ajusto en el día.
Con estas tres rutas el bot puede cerrar ventas sin intervención humana.

---

## Anexo: el link de checkout (confirmado con la documentación de VTEX)

VTEX tiene **carrito compartido**: el orderFormId viaja en la querystring,
entre /checkout/ y #/cart.

> «URL del carrito compartido:
> https://www.{nombredelatienda}.com/checkout/?orderFormId=31155bb8...#/cart»

Fuente: [Qué es el carrito compartido (VTEX Help)](https://help.vtex.com/es/docs/tutorials/que-es-el-carrito-compartido)

### Lo que pedimos

En la respuesta de crear carrito y de agregar ítems:

`json
{
  order_form_id: 8f3a...,
  checkout_url: https://rodabo.myvtex.com/checkout/?orderFormId=8f3a...#/cart
}
`

O, si prefieren no armarlo, al menos:

`json
{
  order_form_id: 8f3a...,
  checkout_host: https://rodabo.myvtex.com
}
`

Y el bot arma el link con la plantilla documentada.

### Verificado de nuestro lado

| Prueba | Resultado |
|---|---|
| GET https://rodabo.myvtex.com/checkout/?orderFormId={id}#/cart | 200 |
| GET https://rodabo.myvtex.com/api/checkout/pub/orderForm/{id} | 200 con los ítems del carrito |
| Carrito creado por nosotros con 1 ítem | la API devuelve el ítem y el total |

### Preguntas

1. ¿El dominio para el cliente es 
odabo.myvtex.com o 
oho.com.bo?
2. ¿Confirman que el link abre el carrito correcto en un navegador sin
   cookies (incógnito, otro teléfono)?
3. ¿Quién arma la URL: el integrador o el bot?
