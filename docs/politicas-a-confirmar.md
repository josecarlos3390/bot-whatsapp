# Políticas que falta confirmar antes de operar con clientes

Los artículos de la base de conocimiento ya no dicen "contenido de ejemplo",
pero varios datos **los escribió el equipo del proyecto y nadie los validó
todavía**. Si alguno está mal, el bot va a prometer algo que el negocio no
cumple.

Revisá esta lista con el área que corresponda y corregí el archivo.

## Garantías — `knowledge/garantias.md`

| Dato | Valor actual | ¿Confirmado? |
|---|---|---|
| Línea blanca y electrónica | 12 meses | ⬜ |
| Muebles y colchones | 6 meses | ⬜ |
| Herramientas eléctricas | 6 meses | ⬜ |
| Herramientas manuales | 3 meses | ⬜ |
| Plazo de respuesta técnica | hasta 5 días hábiles | ⬜ |

## Devoluciones — `knowledge/devoluciones.md`

| Dato | Valor actual | ¿Confirmado? |
|---|---|---|
| Cambio por arrepentimiento | 7 días desde la entrega | ⬜ |
| Reembolso | mismo medio de pago | ⬜ |
| Colchones e higiene | sin cambio por arrepentimiento | ⬜ |

## Pagos — `knowledge/pagos.md`

| Dato | Valor actual | ¿Confirmado? |
|---|---|---|
| Precios incluyen IVA | sí | ⬜ |
| Recargo por tarjeta | no | ⬜ |
| Cuotas sin interés | según banco y producto | ⬜ |
| Medios aceptados | efectivo, débito, crédito, transferencia, QR | ⬜ |

## Reservas — `knowledge/reservas.md`

| Dato | Valor actual | ¿Confirmado? |
|---|---|---|
| Seña | 30 % del valor | ⬜ |
| Vigencia de la reserva | 48 horas | ⬜ |

## Envíos — `knowledge/envios.md`

| Dato | Valor actual | ¿Confirmado? |
|---|---|---|
| Santa Cruz capital | Bs 30 | ⬜ |
| Santa Cruz provincias (50 km) | Bs 50 | ⬜ |
| La Paz y Cochabamba | Bs 45 | ⬜ |
| Resto del país | Bs 70 | ⬜ |
| Envío gratis desde | Bs 1.500 | ⬜ |

## Cómo corregir un dato

1. Abrí el archivo del área (por ejemplo `knowledge/garantias.md`).
2. Cambiá el número.
3. Validá:

```powershell
.\.venv\Scripts\python.exe -m scripts.validar_conocimiento
```

4. Reiniciá el servicio:

```powershell
Restart-Service RohoBot
```

O hacelo desde la consola, en **Conocimiento**, escribiéndole al asistente:
*"la garantía de línea blanca es de 12 meses"*.

## Riesgo de no confirmarlo

| Si el dato está mal | Consecuencia |
|---|---|
| Garantía más larga que la real | Reclamos que el negocio no cubre |
| Envío más barato que el real | Pérdida en cada venta |
| Recargo que sí existe y no se informa | Reclamo del cliente al pagar |
| Seña distinta a la real | Reservas que no se sostienen |
