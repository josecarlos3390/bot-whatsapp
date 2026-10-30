# Cómo agregar información a la base de conocimiento

La base de conocimiento son los archivos `.md` de la carpeta `knowledge/`.
Lo que se escribe ahí es lo que el bot usa para responder sobre políticas,
envíos, garantías y **cómo recomendar productos**.

## Para encargados de área (sin tocar código)

1. Abrí la carpeta `knowledge/`.
2. Copiá un archivo existente como plantilla (por ejemplo `envios.md`).
3. Cambiá el nombre por algo claro: `garantia-heladeras.md`.
4. Completá el encabezado y el contenido.
5. Validá antes de publicar:

```powershell
.\.venv\Scripts\python.exe -m scripts.validar_conocimiento
```

6. Reiniciá el servicio para que el bot lo tome:

```powershell
Restart-Service RohoBot
```

## Formato obligatorio

```markdown
---
title: Garantía de heladeras
status: published
tags: garantia, heladera, refrigerador, cambio, reparacion
---

# Garantía de heladeras

- Texto de la política, en frases cortas.
- Cada punto debe poder responderse solo.
```

| Campo | Para qué |
|---|---|
| `title` | Cómo se llama el artículo en el panel |
| `status` | `published` (lo usa el bot), `draft` (no) |
| `tags` | Palabras con las que el cliente lo va a disparar |
| `sample` | `true` si es un ejemplo; el panel lo marca |

## Reglas de contenido

| Sí | No |
|---|---|
| Frases cortas y concretas | Párrafos largos |
| Datos verificados | Precios inventados |
| Fechas de vigencia | "Próximamente" |
| Una idea por punto | Mezclar políticas |

## Recomendaciones de compra (guía técnica)

La guía de compra (`knowledge/guia-compra.md`) tiene las tablas que el bot
usa para preguntar antes de recomendar:

| Producto | Pregunta | Dato que usa |
|---|---|---|
| Aire acondicionado | ¿Cuántos m²? | BTU del equipo |
| Heladera | ¿Cuántas personas? | Litros |
| Lavadora | ¿Cuántas personas? | Kilos |
| Televisor | ¿A qué distancia? | Pulgadas |
| Colchón | ¿Una o dos personas? | Plazas |
| Pintura | ¿Cuántos m² de pared? | Litros |
| Cortina | ¿Ancho de la ventana? | Medida |
| Taladro | ¿Uso casero o profesional? | Tipo |

Si querés que el bot pregunte un dato nuevo (por ejemplo, largo de una mesa),
hay que pedirlo al equipo técnico: esa pregunta vive en el código
(`app/services/tech_guide.py`) porque además busca el tamaño correcto.

## Qué NO va en la base

- Precios y stock: salen del catálogo en tiempo real.
- Datos de clientes.
- Textos de campañas con fecha corta: para eso están las ocasiones del panel.

## Errores comunes

| Error | Consecuencia |
|---|---|
| Sin encabezado `---` | El artículo se ignora |
| `status: borrador` | No se usa (tiene que ser `published`) |
| Tags vacíos | El bot no lo encuentra |
| Un archivo por tema mezclado | Responde mal o incompleto |
