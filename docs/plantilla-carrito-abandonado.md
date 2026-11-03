# Plantilla de WhatsApp: carrito sin terminar

Para escribirle a un cliente **después de 24 horas** sin que él escriba, Meta
exige una **plantilla aprobada**. El texto es fijo; los datos van como
variables.

## Por qué hacen falta las dos cosas

| Situación | Qué se puede enviar |
|---|---|
| El cliente escribió en las últimas 24 h | Mensaje libre (el bot lo arma con los datos de la base) |
| Pasaron más de 24 h | **Solo plantilla aprobada** |

Por eso el sistema usa:
- **Ventana abierta** → texto generado desde la base (productos, cantidades, total).
- **Ventana cerrada** → plantilla con las mismas variables.

## Texto para presentar en Meta

**Nombre:** `carrito_sin_terminar`
**Categoría:** Utilidad (Utility)
**Idioma:** Español (es)

**Encabezado:** (ninguno)

**Cuerpo:**

```
Hola {{1}}, quedaron {{2}} artículo(s) en tu carrito, entre ellos {{3}}.
El total es Bs {{4}}.

¿Querés que lo terminemos? Respondé SÍ y te ayudo a cerrar la compra.
```

**Pie:** (ninguno)

**Botones:** ninguno (el cliente responde con texto: *SÍ*)

## Variables

| Variable | Qué se envía | Ejemplo |
|---|---|---|
| `{{1}}` | Primer nombre del cliente | `JoseKa` |
| `{{2}}` | Cantidad de artículos distintos | `3` |
| `{{3}}` | Nombre del primer producto | `Impermeabilizante Picasso 3,6 L` |
| `{{4}}` | Total en bolivianos | `1.890` |

## Por qué esta redacción

| Regla de Meta | Cómo se cumple |
|---|---|
| No puede ser promocional | No hay descuento ni oferta: es un recordatorio |
| Debe tener sentido sin la conversación previa | Dice qué quedó y el total |
| Una sola llamada a la acción | “Respondé SÍ” |
| Sin texto engañoso | No dice “tu pedido está listo” (no lo está) |

## Cómo activarla en el sistema

1. Meta Business → WhatsApp → **Plantillas de mensajes** → Crear.
2. Copiar el cuerpo con las variables `{{1}}` … `{{4}}`.
3. Esperar la aprobación (suele tardar minutos u horas).
4. En `.env`:

```
CART_REMINDER_ENABLED=true
CART_REMINDER_HOURS=3
CART_TEMPLATE_NAME=carrito_sin_terminar
CART_TEMPLATE_LANG=es
```

5. Programar el envío (ver abajo).

## Cómo se envía

```powershell
# Ver qué se mandaría (no envía)
.\.venv\Scripts\python.exe -m scripts.recordar_carritos

# Enviar de verdad
.\.venv\Scripts\python.exe -m scripts.recordar_carritos --enviar

# Cambiar la espera (por defecto 3 horas)
.\.venv\Scripts\python.exe -m scripts.recordar_carritos --horas 6 --enviar
```

## Reglas que aplica el sistema

| Regla | Por qué |
|---|---|
| Un recordatorio por carrito cada **7 días** | Evita spam |
| No se envía si el bot está **pausado** (caso con asesor) | No pisar al humano |
| No se envía si el carrito **no tiene artículos** | No hay nada que recordar |
| Se registra cada envío en `cart_reminders` | Auditoría y control de duplicados |

## Qué pasa cuando el cliente responde

Si escribe **SÍ** o **retomar carrito**, el bot abre su carrito y sigue donde
estaba. Ese camino ya funciona (acción `cart`).

## Pendiente de decisión

- **Horario de envío**: hoy no se controla. Conviene no mandar de madrugada.
- **Frecuencia**: 7 días entre recordatorios es un valor inicial, no una regla del negocio.
- **Descuento de recuperación**: si marketing quiere ofrecer uno, cambia la
  categoría de la plantilla y Meta la revisa distinto.
