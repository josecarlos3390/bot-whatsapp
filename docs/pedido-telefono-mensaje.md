# Mensaje para el integrador (copiar y enviar)

---

Hola, gracias por la validación. Confirmamos el mismo resultado de nuestro
lado: `email` y `document` son filtrables; `phone`, `homePhone` y
`businessPhone` devuelven 403. **No hace falta crear la ruta por teléfono.**

Usamos el email como segunda llave, con la salvedad que ustedes marcaron: no
es identificador único, así que solo se usa después de que el cliente se
identifica y siempre verificando la coincidencia.

**Pero encontramos un problema que conviene revisar:**

`GET /api/sap/customers/{term}/purchases` no resuelve solo por documento:
también acepta el **número de secuencia** del pedido.

Ejemplo real:

```
GET /api/sap/customers/500195/purchases
→ devuelve el pedido 1672200500195-01
```

Pero ese pedido **no pertenece al documento 500195**: su
`clientProfileData.document` es **5403339**, y `500195` es únicamente la
secuencia del pedido.

Riesgo: un cliente que escribe un número de 6 dígitos que coincide con la
secuencia de otro pedido recibe **un pedido ajeno**.

**Qué hicimos de nuestro lado:** antes de mostrar cualquier pedido comparamos
el `clientProfileData.document` (o el `phone`/`email` según la llave usada)
con el dato que dio el cliente. Si no coincide, no se muestra y se ofrece un
asesor. Ya está en producción.

**Lo que queremos saber:**

1. ¿El endpoint puede restringirse a **documento y email**, sin resolver por
   secuencia? Es la opción más segura.
2. Si la búsqueda por secuencia se usa para algo, ¿se puede separar en otra
   ruta explícita, por ejemplo `/orders/by-sequence/{numero}`?
3. ¿Nos pueden confirmar qué prioridad usa hoy? (¿prueba documento y, si no
   encuentra, secuencia?)
4. ¿El `email` filtrable es el de la cuenta o el de la orden? Vimos pedidos
   con correos anónimos `...@ct.vtex`, que no sirven como llave.

Con eso cerramos el tema de identificación de pedidos.

Gracias.
