# Despliegue

## Opción recomendada: Render o Railway

Un solo servicio con:

- FastAPI,
- consola React en `/console/`,
- webhook de WhatsApp,
- PostgreSQL,
- SSE.

Ventajas: mismo dominio, cookies sin CORS y webhook estable.

### Build

Usar el `Dockerfile` del repositorio. El contenedor:

1. compila `admin-web`,
2. instala dependencias Python,
3. ejecuta `alembic upgrade head`,
4. arranca Uvicorn en `$PORT`.

### Variables

```env
PUBLIC_BASE_URL=https://tu-servicio.onrender.com
DATABASE_URL=postgresql+asyncpg://usuario:clave@host:5432/roho
ADVISOR_SESSION_SECRET=...
WA_ACCESS_TOKEN=...
WA_PHONE_NUMBER_ID=...
WA_VERIFY_TOKEN=...
WA_APP_SECRET=...
DEEPSEEK_API_KEY=...
SAP_SL_URL=...
SAP_COMPANY_DB=...
SAP_USER=...
SAP_PASSWORD=...
```

### Webhook

```text
https://tu-servicio.onrender.com/webhooks/whatsapp
```

Verificar el token con `WA_VERIFY_TOKEN`.

## Docker

El `Dockerfile` es multi-stage:

1. `web`: instala `admin-web`, ejecuta `pnpm build:console` y genera `dist`.
2. `runtime`: instala Python, copia `admin-web/dist` y sirve la consola en
   `/console/`.

La imagen no necesita Node en producción.

```powershell
docker compose up --build
```

La consola queda en:

```text
http://localhost:8000/console/
```

`PUBLIC_BASE_URL` debe ser la URL pública real para que los links de pago y el
webhook funcionen detrás de un túnel o proxy. en un VPS

```bash
docker compose up -d --build
```

Abre:

```text
http://IP-DEL-VPS:8000/console/
```

Para HTTPS, poner Caddy o Nginx delante y apuntar el webhook al dominio.

## PostgreSQL

El proyecto usa `asyncpg`. En Docker Compose ya hay un PostgreSQL con volumen.
Para migrar datos desde SQLite, exportar e importar o empezar con una base nueva.

Schema:

```bash
alembic upgrade head
```

## Vercel

Vercel sirve solo el frontend React. No es recomendable para el backend porque:

- el webhook necesita un proceso siempre activo,
- SSE no encaja con serverless,
- SQLite no es persistente,
- habría CORS y cookies cross-site.

## Celular

La consola es responsive. Abrir desde el navegador:

```text
https://tu-dominio/console/
```

No requiere app.
