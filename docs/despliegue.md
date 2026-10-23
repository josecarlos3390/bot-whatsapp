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

## Integrador SAP (integration-paas)

El bot no habla con SAP: escribe y lee por el integrador (`SAP_MODE=paas`).

```env
SAP_MODE=paas
SAP_PAAS_URL=http://127.0.0.1:5050
SAP_PAAS_API_KEY=<api key del tenant>
SAP_PAAS_TENANT=RETAIL_QA5
SAP_WRITE_ENABLED=true
SAP_DEFAULT_CARD_CODE=<socio consumidor final>
```

Dos avisos:

- **Docker:** `127.0.0.1` dentro del contenedor es el propio contenedor. Usar
  `SAP_PAAS_URL=http://host.docker.internal:5050` (el `docker-compose.yml` ya
  declara `extra_hosts`). Lo mismo vale para `RABBITMQ_URL`.
- **Orden de despliegue:** primero el integrador (expone
  `/api/sap/business-partners` y el alta de pedido con centros de costo),
  después el bot. Con un integrador viejo, SAP responde
  `(17) Falta Centro de Costo en la línea`.

Republicar el integrador (PowerShell **como administrador**):

```powershell
powershell -ExecutionPolicy Bypass -File C:\ProyectosPython\integrator-paas\scripts\redeploy.ps1
```

Verificar: `curl http://localhost:5050/health/ready`.

## Windows sin permisos de administrador

Instalación actual: API en el puerto **8010** (el 8000 lo usa PeopleCounter) con
un quick tunnel de Cloudflare y reinicio automático.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\serve.ps1
powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -Port 8010
powershell -ExecutionPolicy Bypass -File scripts\serve.ps1 -NoTunnel
```

El script:

- levanta uvicorn y cloudflared, y reinicia cualquiera que se caiga;
- escribe la URL del túnel en `.tools\tunnel-url.txt`;
- cuando el túnel estrena URL, actualiza `PUBLIC_BASE_URL` en `.env` y reinicia
  la API para que los links de pago sigan siendo válidos;
- **sincroniza el catálogo** al arrancar y cada 24 horas, según `SAP_MODE`:
  con `vtex` corre `scripts/sync_vtex` y luego `scripts/sync_vtex_promotions`
  (no necesita `SAP_USER`); con `paas`/`service_layer` corre
  `scripts/sync_catalog`. Se desactiva con `-NoCatalogSync`. La marca de la
  última sincronización queda en `.tools\last-sync.txt` y el log en
  `.tools\sync.log`.

El catálogo local es el índice de búsqueda del bot: sin sincronizar, las
búsquedas por texto no devuelven nada. La primera carga completa son ~29.700
artículos y tarda unos 4 minutos.

Arranque al iniciar sesión: acceso directo `ROHO Bot.lnk` en
`shell:startup`. Logs en `.tools\bot.out.log`, `.tools\bot.err.log` y
`.tools\cloudflared.log`.

Parar todo:

```powershell
Get-Process cloudflared | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*port 8010*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Como servicio (requiere administrador)

Con NSSM, disponible en este servidor:

```powershell
nssm install ROHO-Bot "C:\ProyectosPython\chatbot-whatsapp\.venv\Scripts\python.exe" `
  "-m uvicorn app.main:app --host 127.0.0.1 --port 8010"
nssm set ROHO-Bot AppDirectory "C:\ProyectosPython\chatbot-whatsapp"
nssm set ROHO-Bot AppEnvironmentExtra "SAP_PAAS_URL=http://127.0.0.1:5050"
nssm start ROHO-Bot
```

Con un servicio de Windows el bot sobrevive al cierre de sesión, que es lo
recomendado para producción.

### Endurecer antes de publicar

- `APP_ENV=production` desactiva `/dev/simulate` (hoy permite inyectar mensajes
  y crear pedidos a cualquiera que conozca la URL).
- Con quick tunnel la URL cambia en cada reinicio: para un webhook estable usar
  un túnel con nombre sobre un dominio propio, o publicar detrás de Nginx/Caddy.

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
