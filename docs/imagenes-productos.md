# Imágenes de productos

SAP no trae imágenes. La mejor forma es **no depender del ERP**: mantener un
mapa SKU → URL en la base local y publicar las imágenes en un CDN.

## Recomendación

1. Conseguir imágenes del proveedor, del fabricante o sacarlas en tienda.
2. Subirlas a un bucket/CDN público (S3, R2, Cloudinary o similar).
3. Nombrarlas por SKU:

```text
DCHDCRC200193.jpg
DCHDCRC200193-2.jpg
```

4. Cargar un CSV con el mapeo.
5. El bot y el catálogo nativo usan la URL pública.

No guardar binarios en la base. Guardar solo la URL.

## Formato CSV

```csv
sku,image_url,alt,position,is_primary
DCHDCRC200193,https://cdn.example.com/roho/maceta-husik.jpg,Maceta Husik,1,true
```

Importar:

```powershell
python -m scripts.import_images --csv data/images.csv --dry-run
python -m scripts.import_images --csv data/images.csv
```

El script:

- valida SKU contra el catálogo,
- valida URL http/https,
- crea o actualiza `product_images`,
- marca la principal,
- actualiza `catalog_items.image_url`.

## Modelo

```text
product_images
  sku, url, alt, position, source,
  is_primary, approved, created_at
```

Permite varias imágenes por SKU y elegir la principal.

## Dónde se ve

- `product:SKU` envía **imagen + ficha + botones**.
- El feed del catálogo nativo usa `image_url`.
- Si no hay imagen, se puede usar un placeholder por categoría.

## Imágenes de ejemplo

Se pueden usar para demo o pruebas, pero:

- Deben ser URLs públicas HTTPS reales.
- No usar `cdn.example.com` (no existe).
- Marcar `source=demo` para poder borrarlas después.
- No presentar una imagen genérica como si fuera el producto exacto.

Si no hay imagen, se puede configurar un placeholder:

```env
PRODUCT_IMAGE_PLACEHOLDER=https://tu-cdn.com/placeholder.jpg
META_CATALOG_PLACEHOLDER_IMAGE=https://tu-cdn.com/placeholder.jpg
```

En este entorno de demo quedó configurado:

```text
https://placehold.co/600x600/EEEEEE/333333/png?text=ROHO
```

Es solo para pruebas. Reemplazarlo por un placeholder propio antes de producción.

La ficha enviará la imagen con el texto **“Imagen referencial”**.

## Imágenes reales desde ROHO

Se cargaron **25 imágenes reales** de productos desde el catálogo público de
ROHO, validando que el nombre del archivo coincida con el SKU local:

```powershell
python -m scripts.import_roho_images --limit 30 --per-category 5
```

Resultado:

- 25 imágenes con `source=roho`.
- Las imágenes demo de esos SKUs se reemplazaron.
- La ficha ya no dice “Imagen referencial” para esos productos.

La URL queda pública (`roho.com.bo/wp-content/uploads/...`), así que WhatsApp la
puede descargar.

> Las imágenes son del catálogo público de ROHO. Para producción, confirmar
> derechos de uso y preferir copiarlas a un CDN propio.

## Imágenes demo cargadas

Se cargaron 50 imágenes por categoría con:

```powershell
python -m scripts.load_demo_images --limit 50
```

Cada SKU tiene una URL tipo:

```text
https://placehold.co/600x600/EEEEEE/333333/png?text=FERRETERIA
```

Quedan con `source=demo`, por lo que la ficha muestra **“Imagen referencial”**.
Para borrarlas después:

```sql
DELETE FROM product_images WHERE source = 'demo';
```

No son fotos reales del producto: son una ayuda visual para demo.

Para producción conviene un placeholder por categoría, no uno genérico.

## Requisitos de WhatsApp

- URL pública HTTPS, sin login.
- JPEG o PNG.
- Ideal 500×500 o más, cuadrada.
- Sin texto ni marcas de agua.
- Si la imagen no carga, WhatsApp puede rechazar el mensaje.

## Estrategia por etapas

### Ahora

- CSV manual.
- URL externa o CDN.
- Placeholder si falta.

### Cuando haya volumen

- Bucket propio + CDN.
- Conversión a JPEG/WebP y miniaturas.
- Validación de que la URL responde 200.
- Aprobación por categoría.

### Más adelante

- Feed automático del proveedor.
- Asociación por código de barras.
- Detección de imágenes duplicadas.
- Scraping solo con permiso/licencia.

## Lo que falta

- Placeholder por categoría.
- Validar que la URL responde y descargar una copia.
- Miniaturas.
- Interfaz de carga para el equipo.
