# Base de conocimiento en archivos

Para información que **no está en SAP** (envíos, garantías, devoluciones,
horarios, direcciones, pagos), el bot lee archivos Markdown.

## Formato

```markdown
---
title: Envíos
status: published
tags: envio, delivery, domicilio
---

## Cobertura
Entregamos en Santa Cruz y Warnes.

## Plazo
2 a 4 días hábiles.
```

- `status: published` → el bot lo usa.
- `status: draft` → no se usa. Sirve para completar sin inventar.
- `tags` separados por coma.

Carpeta por defecto:

```text
knowledge/
```

## Recargar

El bot recarga automáticamente si cambia la fecha de modificación. Para forzar:

```http
POST /admin/knowledge/reload
```

Y para ver qué artículos hay:

```http
GET /admin/knowledge
```

Requieren `X-Admin-Token`.

## Cómo lo usa el agente

Herramienta `search_knowledge(query)`:

- busca por título, tags y contenido,
- solo artículos `published`,
- devuelve hasta 3 artículos.

Si no hay resultados, el prompt obliga a decir:

> “No tengo esa información confirmada. ¿Querés que te derive con un asesor?”

No se inventan políticas ni plazos.

## Por qué archivos y no RAG todavía

- Son pocos documentos.
- Se editan sin tocar código.
- Se versionan en Git.
- Búsqueda por palabras es suficiente.
- Cuando crezcan, se migra a PostgreSQL con full-text/pgvector sin cambiar la
  herramienta del agente.

## Qué poner y qué no

**Sí:**

- cobertura y costos de envío,
- plazos,
- garantía,
- devoluciones,
- direcciones y horarios,
- medios de pago,
- reglas internas.

**No:**

- precios y stock (SAP manda),
- datos personales,
- promociones que no estén en SAP.

## Estado actual

Los archivos están en `draft` con `[COMPLETAR]`. Hasta que se completen y pasen a
`published`, el bot responderá que no tiene la información.
