# Mensaje para el integrador (copiar y enviar)

---

Hola, gracias por la respuesta. Confirmo que el teléfono **ya lo tenemos** de
nuestro lado: el bot lo toma de `contacts.phone_e164` y arma las variantes
(`59169006969`, `69006969`, `069006969`). Ese punto está resuelto.

Lo que nos falta es la **otra mitad**: que el PaaS resuelva pedidos por
teléfono, igual que ya resuelve por documento.

**Hoy funciona:**

```
GET /api/sap/customers/500195/purchases   → 1 pedido
```

**Hoy no funciona (devuelve vacío):**

```
GET /api/sap/customers/59169006969/purchases   → vacío
GET /api/sap/customers/69006969/purchases      → vacío
GET /api/sap/customers/069006969/purchases     → vacío
GET /api/sap/customers/59169006969            → vacío
```

**Lo que necesitamos:**

```
GET /api/sap/customers/{telefono}/purchases
GET /api/sap/customers/{telefono}
```

o bien un parámetro en el endpoint que ya existe:

```
GET /api/sap/customers/by-phone?phone=59169006969
```

**Para poder avanzar necesitamos saber:**

1. ¿Dónde está guardado el teléfono en VTEX/SAP? (Master Data CL:
   `homePhone`, `phone`, `businessPhone`; SAP: `Cellular`, `Phone1`, o dentro
   de la dirección.)
2. ¿Ese campo es consultable? ¿Con qué formato lo espera: `59169006969`,
   `69006969` o `069006969`?
3. Si el teléfono no es consultable, ¿podemos resolver por **email** o
   solamente por documento?
4. ¿Se puede agregar el parámetro `?phone=` al endpoint de compras actual, en
   lugar de crear una ruta nueva?

**Por qué importa:** el cliente escribe por WhatsApp, así que el teléfono es el
único dato que ya tenemos sin pedirle nada. Si el PaaS lo resuelve, puede ver
su pedido sin escribir el número de orden ni el CI.

Si no es viable, decinos y el bot sigue pidiendo CI/NIT (ya funciona así).

Gracias.
