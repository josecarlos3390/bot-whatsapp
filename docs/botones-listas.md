# Botones y listas en WhatsApp

El bot usa mensajes interactivos para las acciones más comunes, sin depender del
LLM para interpretar texto libre.

## Acciones rápidas

Saludo (`hola`, `menu`, `inicio`):

- `catalog` — Ver catálogo / seguir comprando
- `cart` — Mi carrito
- `human` — Asesor

Carrito:

- `catalog` — Seguir comprando
- `human` — Asesor

Después de un pedido:

- `catalog` — Ver catálogo
- `human` — Asesor

Los IDs se manejan en `Agent.handle` antes de llamar al LLM.

## Reglas

- Máximo 3 botones.
- Título máximo 20 caracteres.
- Un mensaje interactivo por envío.
- No usar botones para confirmar pagos: el checkout sigue siendo explícito.

## Listas

`Outbound(kind="list")` y `WhatsAppClient.send_list` están disponibles para
categorías o variantes. Formato:

```python
Outbound(
    kind="list",
    text="Elegí una categoría",
    button_text="Ver categorías",
    sections=[
        {
            "title": "Ambientes",
            "rows": [
                {"id": "cat:sala", "title": "Sala"},
                {"id": "cat:cocina", "title": "Cocina"},
            ],
        }
    ],
)
```

## Catálogo por botones

- `catalog` → lista de categorías reales con stock.
- `cat:<categoría>` → lista de productos de esa categoría.
- `product:<SKU>` → ficha corta con precio, stock y botón **Agregar 1**.
- `add:<SKU>:<cantidad>` → agrega al carrito y muestra el total.

Probado con datos locales:

```text
catalog → DECO HOGAR, FERRETERIA, ELECTRICIDAD...
cat:Filtros → FILTRO 2091..., FILTRO C/GRIFO...
product:HRRSGID060055 → Bs 169.00, stock 11, Agregar 1
add:HRRSGID060055:1 → carrito Bs 169.00
```

## Qué falta

- Lista de tiendas.
- Botones por producto: “Otra opción” ya existe; falta “Ver más fotos”.
- Handoff con notificación a asesor.
- Categorías con nombres más amigables (hoy son las de SAP).
