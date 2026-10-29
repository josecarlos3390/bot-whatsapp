# Pedido al integrador: búsqueda de pedidos por teléfono

## Qué necesitamos

Un criterio de búsqueda por **teléfono** en el detalle del cliente y en sus
compras, equivalente al que ya existe por documento.

Hoy el bot puede consultar:

```
GET /api/sap/customers/{documento}/purchases
GET /api/sap/customers/{documento}
```

Y queremos que también resuelva con el teléfono:

```
GET /api/sap/customers/{telefono}/purchases
GET /api/sap/customers/{telefono}
```

## Por qué

El bot ya conoce el teléfono del cliente: es el número de WhatsApp desde el
que escribe. Si el integrador resuelve por teléfono, el cliente **no tiene que
escribir ningún dato** para ver su pedido.

Sin esto, el bot:

1. intenta por teléfono (hoy devuelve vacío),
2. pide el ID del pedido,
3. si no lo tiene, pide CI o NIT.

Cada paso extra es una oportunidad de que el cliente abandone.

## Formatos de teléfono que el bot va a probar

Para un número boliviano `+591 690 06969`, el bot intenta en este orden:

| Variante | Ejemplo |
|---|---|
| Con código de país | `59169006969` |
| Sin código de país | `69006969` |
| Con 0 inicial | `069006969` |

Si el integrador acepta cualquiera de las tres, alcanza.

## Lo que probamos hoy

Con el PaaS actual:

| Consulta | Resultado |
|---|---|
| `GET /api/sap/customers/59169006969/purchases` | vacío |
| `GET /api/sap/customers/69006969/purchases` | vacío |
| `GET /api/sap/customers/59177810716/purchases` | vacío |
| `GET /api/sap/customers/77810716/purchases` | vacío |

El documento sí funciona: `500195` devuelve 1 pedido.

## Comportamiento del bot mientras tanto

- Intenta por teléfono al iniciar el seguimiento.
- Si no encuentra, sigue con el pedido del ID o del CI/NIT.
- Si el cliente dice "mi teléfono es X", lo intenta con las tres variantes y,
  si no resuelve, busca el cliente y usa su documento.

Nada se rompe: el intento falla en silencio y el flujo continúa.
