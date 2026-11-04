# Políticas a validar con el negocio

Los archivos de `knowledge/` que el bot usa para responder sobre garantías,
envíos, pagos y devoluciones están marcados **`sample: true`**: son contenido de
ejemplo, no validado por el negocio.

`knowledge/tarifas-envio.json` lo dice explícito:

> «Tarifas de prueba. Confirmar con el área de logística antes de producción.»

**Riesgo:** el bot afirma plazos, precios y condiciones con seguridad. Si están
mal, el cliente reclama con razón y el reclamo queda por escrito en WhatsApp.

## Las 8 preguntas

### 1. Garantías — plazos por rubro

Hoy el bot dice:

| Rubro | Plazo |
|---|---|
| Línea blanca y electrónica | 12 meses |
| Muebles y colchones | 6 meses |
| Herramientas eléctricas | 6 meses |
| Herramientas manuales | 3 meses |

- ¿Son esos los plazos reales?
- ¿Quién atiende la garantía: ROHO o el servicio técnico de la marca?
- ¿Dónde se lleva el producto?

### 2. Garantías — qué cubre y qué no

Hoy el bot dice que cubre fallas de fabricación y **no** cubre golpes, caídas,
humedad por uso incorrecto ni intervenciones de terceros. Que accesorios y
consumibles tienen cobertura limitada.

- ¿Está bien ese alcance?
- ¿Qué significa "cobertura limitada" para accesorios? (el bot no lo explica)

### 3. Devoluciones y cambios

Hoy el bot dice:

- Cambio por arrepentimiento: **7 días** desde la entrega.
- El producto debe estar sin uso, completo y con embalaje original.
- Se necesita factura o número de pedido.
- **Colchones y artículos de higiene no tienen cambio por arrepentimiento.**

- ¿Son 7 días o es otro plazo?
- ¿Quién paga el flete de la devolución?
- ¿El reembolso es en efectivo, transferencia o nota de crédito? ¿En cuántos días?
- ¿La restricción de colchones aplica igual si viene fallado?

### 4. Costo de envío

Hoy el bot cobra:

| Zona | Costo |
|---|---|
| Santa Cruz capital | Bs 30 |
| Provincias de Santa Cruz (hasta 50 km) | Bs 50 |
| La Paz y Cochabamba (ciudad) | Bs 45 |
| Resto del país | Bs 70 |
| **Gratis desde** | Bs 1.500 |

- ¿Son esas las tarifas vigentes?
- ¿El envío gratis aplica a todo el país o solo a Santa Cruz?
- ¿Hay recargo por peso, volumen o zona alejada?

### 5. Plazos y condiciones de entrega

Hoy el bot dice:

- Entregas **lunes a sábado, 08:00 a 16:00**.
- Pedido normal: **24 horas** después de la confirmación.
- Colchones y somieres: **48 horas**.
- Se entrega en la puerta (planta baja), **sin armado ni instalación**.
- Si no hay nadie, el transportista espera **15 minutos** y vuelve.

- ¿Los plazos son reales?
- ¿Se entrega los sábados?
- ¿Hay armado o instalación como servicio aparte?

### 6. Medios de pago y cuotas

Hoy el bot dice:

- Efectivo en tienda.
- Tarjetas de débito y crédito (Visa, Mastercard).
- Transferencia bancaria con comprobante.
- Pago con **QR**.
- **Cuotas** según banco y promoción vigente.

- ¿Qué medios están realmente habilitados hoy?
- ¿El QR ya funciona o está en pruebas (Cucu)?
- ¿Hay cuotas sin interés? ¿Con qué bancos?
- ¿Se puede pagar contra entrega?

### 7. Precios, IVA y facturación

Hoy el bot dice:

- Los precios **incluyen IVA**.
- No hay recargo por pagar con tarjeta.
- Factura a nombre del titular.
- Para factura con NIT, hay que darlo **al momento de la compra**.

- ¿El precio publicado incluye IVA?
- ¿Se factura siempre o solo si el cliente lo pide?
- ¿El NIT se puede dar después de la compra?

### 8. Reservas con seña

Hoy el bot **ya no ofrece** reservas (se quitó porque no es parte del negocio),
pero el archivo `knowledge/reservas.md` sigue publicado y, si alguien pregunta
"¿puedo reservar?", el bot puede responder con la política vieja:

> Reserva con el 30 % como seña, se mantiene 48 horas.

- ¿Se elimina el archivo o se mantiene la política?

## Preguntas extra (menos críticas, pero útiles)

| Tema | Qué falta definir |
|---|---|
| **Fuera de horario** | ¿Quién atiende los casos derivados después de las 18:00? |
| **Retiro en tienda** | ¿En las 3 sucursales o solo en Av. Banzer? |
| **Cobertura** | ¿Se entrega fuera de Bolivia? |
| **Descuentos** | ¿El bot puede ofrecer descuentos o solo mostrar los vigentes? |
| **Juguetes** | ¿Venden todo el año o solo en temporada (Navidad)? |

## Cómo se corrigen

Cada respuesta validada se reescribe en `knowledge/*.md` y se quita la marca
`sample: true`:

```yaml
---
title: Garantías
status: published
sample: false        ← pasa a contenido oficial
---
```

Mientras diga `sample: true`, el bot está respondiendo con supuestos.
