# Monitoreo del webhook

## Estado en vivo

```http
GET /admin/webhook/status
```

Requiere `X-Admin-Token`.

Devuelve:

```json
{
  "public_base_url": "https://...",
  "last_inbound_at": "2026-10-20T09:38:25",
  "minutes_since_last_inbound": 2,
  "last_outbound_at": "2026-10-20T09:38:25",
  "last_event": {
    "status": "ok",
    "messages": 1,
    "error": null
  },
  "events_24h": {"ok": 12},
  "paused_conversations": 0,
  "pending_handoffs": 1
}
```

También hay una tabla `webhook_events` con:

- recibido,
- firma válida/inválida,
- cantidad de mensajes,
- error.

## Chequeo manual

```powershell
python -m scripts.check_webhook
```

Hace:

1. `GET /health` público.
2. `GET /admin/webhook/status`.
3. Sale con código 1 si algo falla.

Con alerta opcional:

```powershell
python -m scripts.check_webhook --alert-webhook https://n8n.../webhook/alerta
```

## Túnel cambiado automáticamente

Si el quick tunnel cambia de URL, este script:

1. lee la última URL del log de cloudflared,
2. verifica `/health`,
3. verifica el challenge del webhook,
4. actualiza `PUBLIC_BASE_URL` en `.env`,
5. actualiza el callback en Meta.

Una vez:

```powershell
python -m scripts.refresh_tunnel
```

Vigilando cada 60 segundos:

```powershell
python -m scripts.refresh_tunnel --watch
```

Después de actualizar el `.env`, reiniciar la API para que los links de pago usen
la URL nueva.

## Túnel estable

El túnel rápido de Cloudflare **no es estable**: cambia de URL y Meta deja de
enviar eventos.

Para producción, usar un túnel nombrado:

```powershell
cloudflared tunnel login
cloudflared tunnel create roho-bot
cloudflared tunnel route dns roho-bot bot.roho.com.bo
cloudflared tunnel run --url http://localhost:8000 roho-bot
```

Luego actualizar:

```env
PUBLIC_BASE_URL=https://bot.roho.com.bo
```

Y en Meta:

```text
Callback URL: https://bot.roho.com.bo/webhooks/whatsapp
Verify token: WA_VERIFY_TOKEN
```

## Verificar Meta

Con el token de app (`APP_ID|APP_SECRET`):

```http
GET /{app-id}/subscriptions
```

Debe aparecer:

```json
{
  "object": "whatsapp_business_account",
  "callback_url": "https://bot.roho.com.bo/webhooks/whatsapp",
  "active": true
}
```

## Alertas

Monitorear:

- webhook sin eventos por mucho tiempo,
- `webhook_events` con `invalid_signature`,
- `paused_conversations` alto,
- `pending_handoffs` alto,
- errores de envío de WhatsApp.

## Limitación actual

El túnel actual es de prueba. Mientras no haya dominio estable, el webhook puede
cambiar y el bot dejará de recibir mensajes.
