# Búsqueda de productos

La búsqueda combina tres capas para entender al cliente sin depender de un LLM.

## 1. Coincidencia exacta

Busca el término, su plural/singular y su versión sin acentos en:

- nombre,
- descripción,
- keywords,
- SKU,
- marca,
- categoría.

Ejemplo: `colchón` encuentra `COLCHON`.

## 2. Sinónimos

Si la coincidencia exacta no alcanza, expande:

| El cliente dice | También busca |
|---|---|
| living, sala | sofa, sillon, mueble |
| refri, heladera, nevera | refrigerador, línea blanca |
| tv, tele | televisor, pantalla |
| colchón, cama | dormitorio |
| lámpara, foco | iluminación, bombilla |
| ducha, baño | grifería, plomería |
| aire | acondicionador, split |

## 3. Intención de categoría

Para términos ambiguos, prioriza la categoría correcta:

| Término | Categoría |
|---|---|
| living, sala, sofá | MUEBLES |
| refri, tv | LINEA BLANCA |
| colchón | DECO HOGAR |
| ducha | BAÑOS |
| pintura | PINTURA |

Así `living` no devuelve “HOME LIVING” (limpiadores) y `refri` no devuelve
“refrigerante para radiador”.

## 4. Corrección de errores

Si no hay resultados, prueba correcciones por similitud:

- `refirgerador` → `refrigerador`
- `lavadroa` → `lavadora`
- `colchom` → `colchon`

## 5. Búsqueda en caliente en SAP

Cuando ninguna de las capas anteriores encuentra una coincidencia real, el bot
consulta SAP por nombre y **guarda el resultado en su base** para la próxima
consulta.

- Se activa con `SAP_HOT_SEARCH_ENABLED=true` (por defecto) y trae hasta
  `SAP_HOT_SEARCH_LIMIT` artículos.
- La consulta va por el integrador: `GET /api/sap/items?q=...&limit=...`
  (o directo al Service Layer si `SAP_MODE=service_layer`).
- SAP busca texto contiguo y distingue mayúsculas, así que el bot prueba la
  frase, cada palabra y sus variantes de plural.
- La primera consulta tarda ~1 s; las siguientes salen del catálogo local
  (~0,2 s).
- Solo se muestran artículos con stock: si SAP devuelve stock 0, el artículo
  queda guardado pero no se ofrece.

## Qué falta

- Full-text real en PostgreSQL (`tsvector`/`pg_trgm`) para producción.
- Búsqueda semántica/pgvector si crece el catálogo.
- Sinónimos administrables desde archivo o base, no hardcodeados.

Hoy la búsqueda es SQL `ILIKE` optimizada con expansión; funciona bien para
28.000 SKUs y SQLite, con SAP como red de seguridad para lo que falte.
