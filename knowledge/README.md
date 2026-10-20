# Base de conocimiento del bot

Cada archivo `.md` con front matter se carga como artículo. El bot solo usa los
que tienen `status: published`.

## Crear un artículo

```markdown
---
title: Envíos
status: published
tags: envio, delivery, domicilio
---

## Cobertura
...
```

- `status: draft` → no se usa.
- `status: published` → se usa.
- `tags` separados por coma.
- Si falta información, dejar `draft`.

## Recargar

El bot recarga al cambiar los archivos. También se puede forzar:

```http
POST /admin/knowledge/reload
```

con `X-Admin-Token`.

## Temas sugeridos

- `envios.md`: cobertura, costo, plazos, retiro en tienda.
- `garantias.md`: qué cubre, plazo, cómo reclamar.
- `devoluciones.md`: condiciones, plazos, cambios.
- `tiendas.md`: direcciones, horarios, teléfonos.
- `pagos.md`: métodos aceptados, facturación.
- `promociones-internas.md`: reglas que no están en SAP.

No usar este espacio para precios/stock: esos salen de SAP.
