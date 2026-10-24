# Publicar la consola (red interna o internet)

**Objetivo:** que la consola (`/console/`) se abra desde otra VLAN o desde
internet con un nombre propio, por ejemplo `roho-chatbot.gruporoda.com`.

Hoy escucha en `127.0.0.1:8010`: solo el propio servidor puede entrar.

Hay dos caminos. **No son excluyentes**: se puede empezar por la red interna y
después abrir el subdominio hacia afuera.

---

## Opción A — Solo red interna (VLAN)

Recomendada si la consola es para el equipo y no debe quedar expuesta a
internet.

**Datos de este servidor:** IP `10.0.8.16` en la subred `10.0.8.0/24`.

### 1. Escuchar en la red

En `.env`:

```
APP_HOST=0.0.0.0
APP_PORT=8010
```

Y reiniciar el servicio:

```powershell
nssm restart RohoBot
```

`APP_HOST=0.0.0.0` hace que escuche en todas las interfaces. Si se quiere
limitar a una sola, se pone la IP del servidor (ej. `APP_HOST=10.20.5.30`).

### 2. Abrir el puerto solo a la red interna

Como administrador:

```powershell
New-NetFirewallRule -DisplayName "ROHO consola 8010" `
  -Direction Inbound -Protocol TCP -LocalPort 8010 -Action Allow `
  -RemoteAddress 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

Se usan los rangos privados completos: la red (routers/firewall perimetral) es
la que decide qué VLANs llegan al `10.0.8.16`. No abrir a `Any`.

Si se prefiere limitar solo a la subred del servidor, usar
`-RemoteAddress 10.0.8.0/24`.

### 3. Nombre en el DNS interno

Pedir a quien administra el DNS interno un registro **A**:

```
roho-chatbot.gruporoda.com  ->  <IP LAN del servidor>
```

Si no hay DNS interno, se puede usar el archivo `hosts` de cada equipo, pero
no escala.

### 4. Acceso

```
http://roho-chatbot.gruporoda.com:8010/console/
```

Para que no lleve el puerto, hace falta un proxy inverso (IIS, Nginx o Caddy)
escuchando en el 80 y redirigiendo al 8010. Con Caddy es una línea:

```
roho-chatbot.gruporoda.com {
    reverse_proxy 127.0.0.1:8010
}
```

Caddy además emite un certificado interno si se configura una CA propia.

---

## Opción B — Subdominio por Cloudflare Tunnel

Recomendada si `gruporoda.com` está en Cloudflare: **no hay que abrir puertos**
y el certificado HTTPS es automático. Además deja fija la URL del webhook, que
hoy cambia cada vez que se reinicia el túnel rápido.

### 1. Crear el túnel con nombre

```powershell
.tools\cloudflared.exe tunnel login
.tools\cloudflared.exe tunnel create roho-chatbot
.tools\cloudflared.exe tunnel route dns roho-chatbot roho-chatbot.gruporoda.com
```

### 2. Configuración del túnel

`C:\Users\<usuario>\.cloudflared\config.yml`:

```yaml
tunnel: roho-chatbot
credentials-file: C:\Users\<usuario>\.cloudflared\<id-del-tunel>.json
ingress:
  - hostname: roho-chatbot.gruporoda.com
    service: http://127.0.0.1:8010
  - service: http_status:404
```

### 3. Correrlo como servicio

```powershell
.tools\cloudflared.exe service install
```

### 4. Apuntar el webhook a la URL fija

En `.env`:

```
PUBLIC_BASE_URL=https://roho-chatbot.gruporoda.com
```

Reiniciar el servicio y volver a registrar el webhook en Meta con
`scripts/refresh_tunnel.py`. A partir de ahí la URL deja de cambiar.

---

## Seguridad (importante antes de exponer)

| Riesgo | Mitigación |
| --- | --- |
| Consola expuesta a internet | Cloudflare Access (Zero Trust) con lista de correos, o regla WAF por IP |
| Solo debe verse la consola, no la API | Restringir en Cloudflare la ruta `/console*` y `/admin*`; el webhook queda público |
| HTTP sin cifrar | Usar HTTPS siempre: lo da Cloudflare o el proxy inverso |
| Contraseña débil del admin | Cambiarla por una larga y única; no compartirla por WhatsApp |
| Fuerza bruta en el login | Rate limit en Cloudflare o en el proxy (10 intentos/min por IP) |
| Cookies | Ya se marcan `secure` cuando el acceso es HTTPS |

El botón de login ya usa `HttpOnly`, `SameSite=Lax` y `Secure` bajo HTTPS, así
que no hace falta tocar código para eso.

---

## Qué hace falta decidir

1. ¿La consola es **solo para el equipo** (VLAN) o **también desde afuera**?
2. ¿`gruporoda.com` está en Cloudflare? ¿Quién administra el DNS?
3. ¿La subred de la VLAN que debe acceder (ej. `10.20.0.0/16`)?
4. ¿La IP interna fija del servidor del bot?

Con esos cuatro datos se completa la configuración en una sesión corta.
