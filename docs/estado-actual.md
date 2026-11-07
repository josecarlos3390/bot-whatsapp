# Estado del bot — traspaso

**Fecha:** 6 de noviembre de 2026
Última actualización del código: `53e20cd`

## Número y cuenta

| Dato | Valor |
|---|---|
| Número del bot | **+591 69114625** (`ROHO Homecenter BOT`) |
| `WA_PHONE_NUMBER_ID` | `1342823028922443` |
| `WA_WABA_ID` | `1198614182728772` |
| App de Meta | `2438463666347806` (RohoHomecenter) |
| Catálogo de Meta | `1666624888464559` (3.640 productos) |
| Estado del número | CONNECTED · VERIFIED · `account_mode: LIVE` |
| Nombre visible | `ROHO Homecenter BOT` → pedido a `ROHO Homecenter` (en revisión) |
| Token | Usuario del sistema, permanente, en `.env` |

## Qué funciona hoy

| Función | Estado |
|---|---|
| WhatsApp Cloud API | ✅ responde |
| Webhook | ✅ con actualización automática de URL del túnel |
| Catálogo de Meta | ✅ 3.640 productos, conectado a la cuenta |
| Producto nativo (foto + Agregar) | ✅ `200` |
| Catálogo navegable (`catalog_message`) | ✅ `200` |
| Lista nativa en búsquedas (`product_list`) | ✅ `200` |
| Carrito nativo de WhatsApp → carrito del bot | ✅ probado |
| Stock y precio desde VTEX | ✅ en vivo al agregar y al cerrar |
| Flows de facturación y entrega | ✅ publicados |
| Elección tienda/domicilio | ✅ |
| Respaldo de envío (lista → texto) | ✅ |

## Pendientes

| Tema | Estado | Quién |
|---|---|---|
| Método de pago de Meta | ❌ sin tarjeta | Negocio |
| Verificación del negocio | ❌ sin iniciar | Negocio |
| Nombre visible `ROHO Homecenter` | ⏳ en revisión | Meta |
| Venta en VTEX tras el pago | ❌ falta endpoint del PaaS | PaaS |
| QR de pago | ❌ falta proveedor | Negocio |
| Dominio fijo `bot.roho.bo` | ❌ falta IP pública y DNS | Redes |
| Plantillas (recordatorio de carrito) | ❌ | Bot |
| Carrusel con plantilla | ❌ | Bot |

## Problemas conocidos

| Síntoma | Causa | Estado |
|---|---|---|
| `131009 product not found` | Meta rechaza la lista si un SKU no está indexado | ✅ respaldo automático a texto |
| Lista nativa vacía | Filtra productos sin foto (no están en el feed) | ✅ |
| "spider man" no encontraba "Spiderman" | Palabras separadas vs juntas | ✅ concatenación como respaldo |
| El túnel cambia de URL | Cloudflare quick tunnel | ✅ webhook se actualiza solo; feed sigue manual |

## Comandos útiles

```powershell
# estado del número
.\.venv\Scripts\python.exe -m scripts.verificar_numero

# estado de la app, webhook y política
.\.venv\Scripts\python.exe -m scripts.verificar_produccion

# apuntar el webhook a la URL actual del túnel
.\.venv\Scripts\python.exe -m scripts.actualizar_webhook --aplicar

# cambiar número/token del .env
.\.venv\Scripts\python.exe -m scripts.cambiar_numero_whatsapp --numero-id ... --waba ... --token ... --aplicar

# regenerar el CSV del catálogo (con enlaces wa.me)
# ver más abajo

# crear y publicar los Flows
.\.venv\Scripts\python.exe -m scripts.crear_flujos --aplicar

# pruebas
.\.venv\Scripts\python.exe -m pytest -q
```

## Regenerar el CSV del catálogo

```powershell
.\.venv\Scripts\python.exe -X utf8 -c @"
import asyncio, csv, io
from pathlib import Path
from app.db import SessionLocal
from app.services import native_commerce
async def main():
    async with SessionLocal() as s:
        filas, _ = await native_commerce.catalog_feed(s)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(native_commerce.CAMPOS_FEED))
    w.writeheader(); w.writerows(filas)
    Path('.tools/catalogo-roho.csv').write_text(buf.getvalue(), encoding='utf-8')
    print(len(filas), 'productos')
asyncio.run(main())
"@
```

Después se sube a Commerce Manager → Orígenes de datos → subir archivo.

## Documentos

| Documento | Contenido |
|---|---|
| `docs/migracion-numero-real.md` | Cómo se migró el número y qué se aprendió |
| `docs/catalogo-nativo-whatsapp.md` | Catálogo, carrito nativo y sus límites |
| `docs/dominio-fijo.md` | Caddy, DNS y requisitos de red |
| `docs/privacidad/index.html` | Página publicada de privacidad |
| `docs/flows/*.json` | Formularios de facturación y entrega |

## Decisiones tomadas

1. **El carrito es del bot** (`VTEX_CART_ENABLED=false`); VTEX ya no recibe el espejo.
2. **VTEX manda en stock y precio**: se consulta en vivo en cada operación.
3. **El número tuvo que salir de un BSP** (Callbell) para poder operarlo con nuestra app.
4. **Links del catálogo con `wa.me`**, porque el túnel cambia y `/p/{sku}` se rompería.
5. **Los formularios van después del pago**; por ahora el pago se simula.

## Contactos

- PaaS: SLA de retiro en tienda y endpoint para crear la venta en VTEX.
- Redes: IP pública, puertos 80/443 y registro `A` de `bot.roho.bo`.
- Meta: aprobación del nombre visible y verificación del negocio.
