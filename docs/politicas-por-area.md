# Políticas a confirmar, por área

Cada bloque está listo para reenviar al área que corresponde. Las preguntas
están escritas para que la respuesta sea un dato, no una opinión.

Estado de hoy: **8 datos sin validar**. Los tomó el equipo del proyecto; el
bot ya los está usando con clientes.

---

## 1. Comercial / Gerencia de ventas

Responde: plazos de garantía, devolución y reservas.
Archivos: `knowledge/garantias.md`, `knowledge/devoluciones.md`,
`knowledge/reservas.md`

### Preguntas

1. ¿Cuántos meses de garantía damos en **línea blanca y electrónica**?
   Hoy: **12 meses**.
2. ¿Y en **muebles y colchones**? Hoy: **6 meses**.
3. ¿Y en **herramientas eléctricas**? Hoy: **6 meses**.
4. ¿Y en **herramientas manuales**? Hoy: **3 meses**.
5. ¿Cuántos días tiene el cliente para **devolver por arrepentimiento**?
   Hoy: **7 días** desde la entrega.
6. ¿Los **colchones** tienen devolución por arrepentimiento?
   Hoy: **no** (por higiene).
7. ¿Qué porcentaje de **seña** pedimos para reservar? Hoy: **30 %**.
8. ¿Cuánto tiempo se guarda una **reserva** sin pagar? Hoy: **48 horas**.

### Riesgo si el dato está mal

| Dato equivocado | Qué pasa |
|---|---|
| Garantía más larga que la real | El bot promete cobertura que el negocio no da |
| Devolución más amplia | Reclamos fuera de política |
| Seña distinta | El cliente paga algo que no corresponde |

---

## 2. Logística / Operaciones

Responde: tarifas y tiempos de entrega.
Archivo: `knowledge/envios.md`

### Preguntas

1. **Santa Cruz capital**: ¿cuánto cuesta el envío? Hoy: **Bs 30**.
2. **Provincias de Santa Cruz (hasta 50 km)**: hoy **Bs 50**.
3. **La Paz y Cochabamba (ciudad)**: hoy **Bs 45**.
4. **Resto del país**: hoy **Bs 70**.
5. ¿Desde qué monto el **envío es gratis**? Hoy: **Bs 1.500**.
6. ¿El **retiro en tienda** sigue sin costo? Hoy: **sí**.
7. ¿El plazo de entrega sigue siendo **24 horas** (48 para colchones)?

### Riesgo si el dato está mal

| Dato equivocado | Qué pasa |
|---|---|
| Envío más barato | Pérdida directa en cada venta |
| Envío gratis a un monto bajo | Margen destruido |
| Plazo más corto | Reclamos por demora |

---

## 3. Administración / Finanzas

Responde: impuestos, recargos y medios de pago.
Archivo: `knowledge/pagos.md`

### Preguntas

1. Los precios publicados, ¿**incluyen IVA**? Hoy: **sí**.
2. ¿Hay **recargo** por pagar con tarjeta? Hoy: **no**.
3. ¿Qué **medios de pago** aceptamos hoy? Hoy: efectivo, débito, crédito,
   transferencia y QR.
4. ¿Siguen vigentes las **cuotas sin interés**? ¿Con qué bancos?

### Riesgo si el dato está mal

| Dato equivocado | Qué pasa |
|---|---|
| Decir "sin recargo" y sí haberlo | Reclamo del cliente al pagar |
| IVA mal informado | Problema tributario y de facturación |
| Cuotas que ya no existen | Cliente exige algo que no se puede dar |

---

## 4. Atención al cliente

Responde: cómo se atienden los reclamos.
Archivos: `knowledge/garantias.md`, `knowledge/contacto.md`

### Preguntas

1. ¿En cuántos **días hábiles** se responde una revisión técnica?
   Hoy: **hasta 5**.
2. ¿El **WhatsApp 72100717** y el **teléfono 3180100** siguen activos?
3. ¿El correo **atencionalcliente@gruporoda.com** sigue siendo el canal?

### Riesgo si el dato está mal

| Dato equivocado | Qué pasa |
|---|---|
| Plazo más corto del real | Cliente espera respuesta que no llega |
| Contacto viejo | El cliente escribe a un canal muerto |

---

## Cómo devolver las respuestas

Con un mensaje por área alcanza. Ejemplo:

> Comercial: garantía 12/6/6/3 meses está bien. Devolución 7 días OK.
> Colchones sin devolución OK. Seña 30 % y 48 h OK.

O directamente en la consola, en **Conocimiento**, escribiéndole al
asistente:

> "la garantía de línea blanca es de 12 meses"

---

## Mientras no estén confirmados

Hay dos caminos:

| Opción | Efecto |
|---|---|
| **Dejar los valores actuales** | El bot responde con datos que pueden estar mal |
| **Sacar el dato del artículo** | El bot dice "te lo confirma un asesor" |

La segunda es más segura. Se hace borrando la línea del artículo y
reiniciando el servicio.
