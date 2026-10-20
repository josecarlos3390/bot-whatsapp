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

## Qué falta

- Full-text real en PostgreSQL (`tsvector`/`pg_trgm`) para producción.
- Búsqueda semántica/pgvector si crece el catálogo.
- Sinónimos administrables desde archivo o base, no hardcodeados.

Hoy la búsqueda es SQL `ILIKE` optimizada con expansión; funciona bien para
28.000 SKUs y SQLite.
