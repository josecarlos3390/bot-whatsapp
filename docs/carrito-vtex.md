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
VTEX_SELLER_ID=1
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

## Fuente de precio y stock

Confirmado con el equipo del PaaS: el bot lee catálogo, precio y stock de
**VTEX a través del PaaS**, y el checkout también es VTEX. **No hay iVend en
ese camino**, así que el precio que muestra el bot y el del checkout salen del
mismo lugar.

⚠️ Si en algún momento iVend pasa a ser la fuente real de stock o precio, la
paridad **deja de estar garantizada** y hay que revisarlo antes de activar el
carrito.

## Antes de activar

| Requisito | Estado |
|---|---|
| Rutas de carrito en el PaaS | ⏳ |
| Dominio de checkout (checkout_url) | ⏳ |
| Validación de punta a punta | ⏳ |
| VTEX_CART_ENABLED=false | ✅ hasta entonces |

## Estado del cierre con el PaaS

Validado el 3/11/2026 contra el PaaS desplegado:

| Punto | Resultado |
|---|---|
| crear | order_form_id nuevo, carrito vacío |
| Aislamiento | dos creaciones → dos carritos distintos |
| gregar | ítem correcto, messages solo de la request |
| consultar | mismo order_form_id, vigente |
| sincronizar | ok, y repetir no duplica |
| limpiar | ok |

Acordado con el PaaS:

```
checkout_url: null
expires_at:   null
TTL:          24 h del lado del bot
SellerId:     1
```

**No hace falta cambiar nada más del contrato.**

### Lo único pendiente: dominio de checkout

Pasos acordados:

1. El PaaS configura Vtex:CheckoutHost y redespliega.
2. Verifican que checkout_url deje de ser null.
3. Avisan para activar VTEX_CART_ENABLED=true temporalmente.
4. Corre el E2E final con el link real.
5. Si funciona, la bandera queda activa.

### Qué prueba el E2E

```
crear                 → order_form_id nuevo y carrito vacío
aislamiento           → dos carritos distintos
agregar               → ítem con precio de VTEX
varios productos      → cantidades por SKU, sin sumar
SKU inexistente       → rechazo informado en messages
consultar             → mismo carrito
sincronizar           → ok
sincronizar dos veces → no duplica
limpiar               → borra los datos de prueba
```

## Detección del pedido (¿el cliente pagó?)

El cliente paga en VTEX. Para enterarse, el bot consulta
`GET /api/vtex/orders` y busca el pedido cuyo `orderFormId` coincide con el
carrito que armó.

```
Cliente paga en la tienda
        ↓
Vuelve a WhatsApp y pide "mi carrito"
        ↓
El bot consulta los pedidos y encuentra el suyo
        ↓
"Tu pedido 500195 ya está registrado y quedó en preparación"
        ↓
El carrito pasa a estado ordered y no se le ofrece el link otra vez
```

Estados traducidos: `payment-pending` → esperando el pago ·
`payment-approved` → pago aprobado · `ready-for-handling` → en preparación ·
`handling` → preparando el envío · `invoiced` → facturado · `canceled` →
cancelado.

### Limitación actual

`GET /api/vtex/orders` **no filtra** por `orderFormId` (devuelve la lista
completa e ignora `limit`). El bot la pide, la guarda 60 s y busca en memoria.

Con 61 pedidos es instantáneo; con miles habrá que pedirle al PaaS:

```
GET /api/vtex/orders?orderFormId=...
```

## El link del cliente

El bot nunca arma la URL: usa la que devuelve el integrador. Cuando exista
el dominio, el mensaje es un **botón de enlace** de WhatsApp:

`
[ Terminar mi compra ]  →  https://rodabo.myvtex.com/checkout/?orderFormId=…
`

⚠️ El link tiene que llevar el orderFormId. …/checkout/#/cart abre el
carrito del navegador, así que un cliente que viene de WhatsApp vería uno
vacío.

## Formato del link: confirmado por el PaaS y por VTEX

`
https://rodabo.myvtex.com/checkout/?orderFormId={id}#/cart
`

- El orderFormId va en la **querystring**, entre /checkout/ y #/cart.
- Funciona **sin cookies**: la API devuelve el carrito en incógnito.
- 
oho.com.bo todavía responde **503** (página de SeedProd): no se usa.
- El PaaS devuelve checkout_url **y** checkout_host. Si falta la URL, el
  bot la arma con el host (de la respuesta o de VTEX_CHECKOUT_HOST).

### Configuración actual

`
VTEX_CHECKOUT_HOST=https://rodabo.myvtex.com
VTEX_CART_ENABLED=false        ← hasta que el PaaS despliegue el formato
`

### Validado

| Prueba | Resultado |
|---|---|
| Carrito de 1 ítem | API devuelve el ítem y el total |
| Carrito de 2 unidades | API devuelve quantity: 2 |
| Link con ?orderFormId= | 200 |
| Sin cookies | funciona |

## Piloto activo (5/11/2026)

Deploy confirmado por el PaaS. La bandera quedó **activa** con un piloto:

`
VTEX_CART_ENABLED=true
VTEX_CHECKOUT_HOST=https://rodabo.myvtex.com
VTEX_CART_PILOT_PHONES=59177810716,59169006969,59179050453,59176012480,59171657810
`

- **Solo esos números** reciben el link de pago.
- El resto sigue igual: el caso pasa a un asesor.
- Para abrirlo a todos: dejar VTEX_CART_PILOT_PHONES vacío.

### Por qué piloto


oho.com.bo sigue devolviendo **503** (página de SeedProd). Los links usan

odabo.myvtex.com hasta que el dominio de marca esté operativo. Cuando el
PaaS cambie CheckoutHost, los links **nuevos** saldrán con el dominio de
marca; los viejos con 
odabo.myvtex.com siguen funcionando.

### Cómo se prueba

1. Escribir al bot desde un número de la lista.
2. Agregar un producto y tocar **Finalizar pedido**.
3. Debe llegar el botón **Terminar mi compra** con el link.
4. Abrirlo en incógnito: el carrito tiene que estar completo.

## Búsqueda libre con sinónimos (VTEX Intelligent Search)

El PaaS agregó GET /api/vtex/search?q={query}&limit={n}, que usa
Intelligent Search y **aplica los sinónimos de la tienda** (fumigador →
pulverizadores, bebote → muñecas) sin replicar los 147 sinónimos en la base.

Cómo quedó integrado en el bot:

`
1. Se busca en el catálogo local (con sus propias variantes).
2. Si devuelve menos de 3 opciones, se consulta /api/vtex/search.
3. Los SKU que existen en la base local se agregan al resultado.
4. Precios, stock y filtros siguen saliendo de la base del bot.
`

| Regla | Detalle |
|---|---|
| Solo búsquedas libres | Si hay filtros (categoría, marca, precio) no se llama |
| Solo si hace falta | Con 3 o más resultados locales no se consulta |
| Sin duplicados | Se descartan los SKU ya mostrados |
| Ignora SKU desconocidos | Un producto que no está en la base se espera al próximo sync |
| No insiste | Si el endpoint no existe (404), deja de llamarse 5 minutos |

### Estado

- Implementado y probado con el endpoint simulado.
- **Falta que el PaaS lo publique en el 5050.**
- Cuando esté, la validación es:

`powershell
.\.venv\Scripts\python.exe -m scripts.validar_busqueda_vtex
`

Prueba «fumigador», «bebote», «muñeca», «taladro» e «hidrolavadora», y avisa
si la búsqueda de VTEX aporta resultados que el catálogo local no tenía.

## Contrato del carrito: sku debe ser el RefId

| Ruta | Devuelve sku |
|---|---|
| POST /api/vtex/cart/{id}/items | el RefId que enviamos (eco) |
| GET /api/vtex/cart/{id} | **id interno de VTEX** (pendiente de corregir) |

El PaaS confirmó el 5/11 que lo corrigió para ADD y GET:

`json
{sku: JGTDOLL030002, sku_id: 8946, quantity: 1, price: 499}
`

**Todavía falta desplegarlo en el 5050.** Mientras tanto el bot traduce el id
interno con CatalogItem.attributes[vtex_sku_id] y, si no lo encuentra,
descarta el ítem (para no mostrar un código en el carrito).

Cuando el GET devuelva el RefId:

1. Correr scripts/validar_carrito_vtex y ver «el GET devuelve el RefId».
2. Retirar el respaldo de 
econciliar (queda anotado en el log cuando se usa).

### Caso borde

Si un SKU no tiene RefId en VTEX, el integrador devuelve el id interno como
respaldo. En ese caso el bot no puede mostrar nombre ni precio y lo omite del
carrito hasta el próximo sync.

### Cerrado el 5/11

El PaaS desplegó el binario nuevo y el GET devuelve el RefId:

`
5. Consultar carrito
   ✓ consulta ok · 3 ítem(s)
   ✓ el GET devuelve el RefId (DCHBANO030191)
`

**Se retiró la traducción con tex_sku_id** y el helper sku_por_vtex_id.
El carrito ahora trabaja solo con RefIds.

Caso borde (SKU sin RefId → VTEX devuelve el id interno): el ítem no coincide
con el catálogo y se omite, para no mostrar un código al cliente.
