# Migración a PostgreSQL

## Estado del servidor

PostgreSQL 16 corre en el puerto **5434** (no el 5432 habitual).

Estado: **migrado**. La base 
oho_bot y su usuario existen, los datos se
copiaron y se validaron (44.478 filas, todas las tablas coinciden). La
conexión del bot ya apunta a Postgres; la base SQLite dev.db queda intacta
como respaldo y para volver atrás cambiando una línea.

## Cuándo conviene migrar

| Situación | Recomendación |
|---|---|
| Antes del piloto, con datos de prueba | ✅ **Ahora**: no hay riesgo de perder conversaciones reales |
| Después del piloto | Hay que hacerlo con el bot en marcha y respaldo doble |
| Si no hay credenciales pronto | Seguir en SQLite: 20 clientes simultáneos, 0 errores medidos |

## Qué mejora con PostgreSQL

| Tema | SQLite | PostgreSQL |
|---|---|---|
| Escrituras simultáneas | una a la vez | muchas |
| Procesos uvicorn | 1 (un solo núcleo) | varios, usa todos los núcleos |
| Búsqueda de texto | básica | `tsvector` (relevancia real) |
| Datos JSON (payloads) | texto | `JSONB` consultable |
| Informes | consultas simples | ventanas, agregados rápidos |

## Pasos

1. **Pedir credenciales** (host `127.0.0.1`, puerto `5434`):
   ```
   base: roho_bot
   usuario: roho_bot
   ```
2. **Crear la base** (con un usuario administrador):
   ```sql
   CREATE DATABASE roho_bot;
   ```
3. **Copiar los datos** (se puede repetir; no toca el origen):
   ```powershell
   .\.venv\Scripts\python.exe -m scripts.migrar_a_postgres `
     --destino "postgresql+asyncpg://roho_bot:CLAVE@127.0.0.1:5434/roho_bot"
   ```
   El script crea el esquema, copia las tablas en orden de dependencia y
   compara la cantidad de filas. Termina con `validación: todas las tablas
   coinciden`.
4. **Cambiar la cadena de conexión** en `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://roho_bot:CLAVE@127.0.0.1:5434/roho_bot
   ```
5. **Reiniciar** el servicio y correr las pruebas:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   .\.venv\Scripts\python.exe -m scripts.auditoria_dialogos
   .\.venv\Scripts\python.exe -m scripts.bench_carga --clientes 20 --mensajes 1
   ```
6. **Volver atrás** es cambiar la línea de `.env` y reiniciar: la base SQLite
   queda intacta todo el tiempo.

## Después de migrar: varios procesos

Con PostgreSQL se puede levantar más de un proceso para usar todos los
núcleos del servidor:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --workers 4
```

Con SQLite **no** se debe: cada proceso abriría su propia conexión y los
bloqueos volverían.

## Lo que no cambia

- Los modelos son los mismos (SQLAlchemy).
- Las migraciones manuales (`ALTER TABLE`) hay que revisarlas: en PostgreSQL
  se pueden usar `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

## Respaldo y restauración

El respaldo diario ya funciona con PostgreSQL:

```powershell
.\.venv\Scripts\python.exe -m scripts.backup_db
```

Deja `backups/<fecha>/roho_bot.dump` (formato personalizado, comprimido),
copia `.env` y `knowledge/`, y conserva las últimas 14 copias.

**Verificar una copia:**

```powershell
.\.venv\Scripts\python.exe -m scripts.backup_db --verificar backups\20261030-050000
```

**Restaurar** (en una base nueva, sin tocar la que está en uso):

```powershell
$env:PGPASSWORD = "..."
& "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" `
  -h 127.0.0.1 -p 5434 -U postgres -d roho_bot_nueva --no-owner `
  backups\20261030-050000\roho_bot.dump
```

Probado: copia de 4,1 MB con 41 tablas, restaurada en una base nueva sin
errores y con los mismos datos (139 mensajes, 384 contactos, 10 reglas).

### Filas huérfanas

Si se borran conversaciones a mano con SQL, quedan filas que apuntan a un
padre inexistente. No afectan al bot pero **impiden restaurar** una copia.

```powershell
.\.venv\Scripts\python.exe -m scripts.limpiar_huerfanos            # informe
.\.venv\Scripts\python.exe -m scripts.limpiar_huerfanos --confirmar
```

Se limpiaron 4.380 filas huérfanas que venían de las pruebas; conviene correr
el informe antes de cada respaldo importante.
