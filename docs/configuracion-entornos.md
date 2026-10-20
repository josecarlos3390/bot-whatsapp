# Configuración por entorno

El código es uno solo para todas las instalaciones. Lo que cambia es el `.env`,
que **no se versiona**: cada máquina guarda el suyo y el repositorio expone el
contrato en [.env.example](../.env.example).

Regla de oro: si el código necesita una variable nueva, se agrega a `.env.example`
con un valor por defecto seguro. Nunca se commitea un `.env` real.

## Perfiles

### Servidor (esta instalación)

SAP real a través del integrador, WhatsApp real y túnel de Cloudflare.

```env
APP_ENV=dev
PUBLIC_BASE_URL=https://<tunel>.trycloudflare.com
DATABASE_URL=sqlite+aiosqlite:///./dev.db
QUEUE_ENABLED=false
SAP_MODE=paas
SAP_PAAS_URL=http://127.0.0.1:5050
SAP_PAAS_API_KEY=<api key del tenant>
SAP_PAAS_TENANT=RETAIL_QA5
SAP_WRITE_ENABLED=true
SAP_LIVE_READS=true
SAP_COSTING_CODE=14304
SAP_COSTING_CODE2=ECO
SAP_COSTING_CODE3=1000
SAP_TAX_CODE=IVA
SAP_DEFAULT_CARD_CODE=<socio consumidor final>
SAP_EVENT_QUEUE_ENABLED=true
WA_DRY_RUN=false
ADMIN_TOKEN=<token largo>
```

### Local (máquina de desarrollo)

Todo simulado: catálogo demo, SAP mock y mensajes en dry-run. No requiere
integrador, RabbitMQ ni credenciales de Meta.

```env
APP_ENV=dev
PUBLIC_BASE_URL=http://127.0.0.1:8000
DATABASE_URL=sqlite+aiosqlite:///./dev.db
QUEUE_ENABLED=false
SAP_MODE=mock
SAP_WRITE_ENABLED=false
SEED_DEMO=true
SAP_EVENT_QUEUE_ENABLED=false
WA_DRY_RUN=true
ADMIN_TOKEN=
```

Con ese perfil `POST /dev/simulate` permite conversar sin WhatsApp.

## Variables que cambian entre perfiles

| Variable | Servidor | Local | Efecto |
|---|---|---|---|
| `SAP_MODE` | `paas` | `mock` | origen de catálogo, precio y stock |
| `SAP_WRITE_ENABLED` | `true` | `false` | habilita crear pedidos en SAP |
| `SAP_PAAS_URL` | integrador | vacío | no se usa en modo mock |
| `SAP_DEFAULT_CARD_CODE` | socio genérico | vacío | clientes sin RUT |
| `SEED_DEMO` | `false` | `true` | carga 24 productos demo |
| `WA_DRY_RUN` | `false` | `true` | no llama a Meta |
| `SAP_EVENT_QUEUE_ENABLED` | `true` | `false` | consumidor RabbitMQ |
| `PUBLIC_BASE_URL` | URL del túnel | `localhost` | links de pago |
| `ADMIN_TOKEN` | obligatorio | opcional | protege `/admin` |

## Cómo sincronizar el código

El repositorio se mantiene con una sola rama de trabajo (`main`). Para llevar
cambios de una máquina a otra:

```powershell
# en la máquina que tiene los cambios
git bundle create version-unica.bundle origin/main..integracion/version-unica

# en la otra
git fetch .\version-unica.bundle integracion/version-unica:integracion/version-unica
git merge integracion/version-unica
```

O directamente con `git push` / `git pull` si hay credenciales configuradas.

## Al desplegar

1. Copiar el `.env` propio de esa máquina (nunca uno ajeno).
2. `alembic upgrade head` si hay migraciones nuevas.
3. Recompilar la consola si cambió `admin-web`: `pnpm build:console`.
4. Reiniciar la API.
