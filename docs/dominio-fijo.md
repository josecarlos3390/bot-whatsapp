# Dominio fijo para el bot (`bot.roho.com.bo`)

El bot hoy usa un túnel de Cloudflare que **cambia de URL en cada reinicio**.
Para producción hace falta una URL estable: la usan el webhook de Meta, el
feed del catálogo y las fichas de producto.

## Lo que tiene que habilitar el equipo de redes

| # | Requisito | Detalle |
|---|---|---|
| 1 | **IP pública fija** | La del servidor del bot (o NAT a su IP interna) |
| 2 | **Puerto 80 abierto** | Solo para el certificado (Let's Encrypt) |
| 3 | **Puerto 443 abierto** | Tráfico HTTPS del bot |
| 4 | **DNS** | Registro `A` de `bot.roho.com.bo` → IP pública |

El puerto **8010 no se expone**: queda escuchando en local y Caddy hace de
frente.

```
Internet
   │  https://bot.roho.com.bo (443)
   ▼
Caddy  ──►  127.0.0.1:8010  (FastAPI)
```

## Paso 1 — DNS

En el panel donde se administra `roho.com.bo`:

```
Tipo:  A
Nombre: bot
Valor: <IP pública del servidor>
TTL:   300
```

Verificar:

```powershell
Resolve-DnsName bot.roho.com.bo
```

## Paso 2 — Instalar Caddy como servicio

Caddy obtiene y renueva el certificado solo.

```powershell
# Descargar caddy.exe y ubicarlo en .tools\
# Instalar como servicio (como administrador)
.tools\caddy.exe service install
.tools\caddy.exe start
```

`C:\ProyectosPython\chatbot-whatsapp\Caddyfile`:

```caddy
bot.roho.com.bo {
    encode gzip

    # El bot escucha en local.
    reverse_proxy 127.0.0.1:8010

    header {
        Strict-Transport-Security "max-age=31536000"
    }
}
```

Recargar:

```powershell
.tools\caddy.exe reload --config Caddyfile
```

## Paso 3 — Firewall de Windows

```powershell
New-NetFirewallRule -DisplayName "Caddy HTTP"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "Caddy HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

## Paso 4 — Verificar

```powershell
# Certificado y respuesta
curl.exe -I https://bot.roho.com.bo/health

# Feed del catálogo
curl.exe -I "https://bot.roho.com.bo/feeds/catalog/<TOKEN>.csv"

# Ficha de producto
curl.exe -I https://bot.roho.com.bo/p/LBLTELE050023
```

Los tres tienen que dar `200` con `HTTP/2`.

## Paso 5 — Cambiar el `.env`

```env
PUBLIC_BASE_URL=https://bot.roho.com.bo
```

Reiniciar el servicio y actualizar el webhook:

```powershell
Restart-Service RohoBot
.\.venv\Scripts\python.exe -m scripts.actualizar_webhook --aplicar
```

## Paso 6 — Meta

### Webhook

Se actualiza solo con el comando de arriba, pero conviene confirmarlo:

👉 [App → WhatsApp → Configuración](https://developers.facebook.com/apps/2438463666347806/whatsapp-business/wa-settings/)

```
URL: https://bot.roho.com.bo/webhooks/whatsapp
```

### Feed del catálogo

👉 Commerce Manager → el catálogo → Fuentes de datos

```
https://bot.roho.com.bo/feeds/catalog/<TOKEN>.csv
Frecuencia: cada 6 horas
```

**Con dominio fijo la URL ya no cambia** y el catálogo se actualiza solo.

## Cuidados

| Riesgo | Mitigación |
|---|---|
| La IP pública cambia | Contratar IP fija |
| El certificado no renueva | Caddy lo hace solo; revisar que 80 esté abierto |
| El servidor se apaga | Servicio de Windows + tarea de arranque |
| Cambia la IP interna | Ajustar el `reverse_proxy` |

## Mientras no esté el dominio

| Tarea | Cómo se hace hoy |
|---|---|
| Catálogo de Meta | Subir el CSV a mano |
| Webhook | Túnel + `scripts.actualizar_webhook` cada vez que rota |
| Fichas de producto | Funcionan con el túnel (cambia la URL) |

**El dominio fijo no es un requisito para probar**, sí para operar sin
sorpresas.
