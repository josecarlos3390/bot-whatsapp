# Plantillas de WhatsApp: encuesta de atención/entrega

Para iniciar una conversación después de la ventana de 24 h, WhatsApp exige una
plantilla aprobada.

## Plantilla actual: atención

```text
Nombre: encuesta_atencion
Categoría: Utility
Idioma: es
```

```text
Hola {{1}}, ¿cómo calificás la atención de tu compra {{2}}? Respondé del 1 al 5.
Gracias por comprar en ROHO.
```

Variables:

- `{{1}}`: nombre del cliente.
- `{{2}}`: número de pedido.

Esta es la que usa `FEEDBACK_TEMPLATE_NAME=encuesta_atencion`.

## Plantilla futura: entrega

```text
Nombre: encuesta_entrega
Categoría: Utility
Idioma: es
```

```text
Hola {{1}}, ¿la entrega de tu pedido {{2}} llegó en el tiempo prometido?
Respondé Sí o No. Gracias por comprar en ROHO.
```

Solo se usa cuando exista un evento real de entrega o se marque manualmente
`POST /admin/orders/{number}/delivered`.

## Botones (opcional)

Quick reply:

- `Sí, llegó bien`
- `No, llegó tarde`

Si se usan botones, el webhook devuelve `button` y el bot debe mapearlo a
`record_feedback(type=delivery, order_number=...)`.

## Creación

1. WhatsApp Manager → Plantillas de mensajes.
2. Crear plantilla → Utility.
3. Idioma Spanish (`es`).
4. Cargar cuerpo y botones.
5. Enviar a revisión.

No crear la plantilla desde código sin confirmación: es una escritura en Meta y
requiere cuenta/WABA de producción.

## Reglas

- Enviar solo a clientes con opt-in.
- Una sola vez por pedido.
- Si el cliente responde, guardar `record_feedback`.
- Si no responde, no insistir.
- Si responde negativamente, ofrecer solución o derivar a humano.
