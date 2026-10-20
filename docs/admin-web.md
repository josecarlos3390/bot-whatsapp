# Consola de asesores (React)

Frontend separado del API para la bandeja de handoffs y la administración de
agentes.

## Stack

- React 19
- Vite
- TypeScript
- Tailwind CSS 4
- Mantine 9 (`AppShell`, navegación y notificaciones)
- React Router
- Componentes estilo shadcn/ui (`src/ui.tsx`) para el contenido existente
- lucide-react y tabler-icons para iconos

## Desarrollo

```powershell
cd admin-web
pnpm install
pnpm dev
```

Abre:

```text
http://127.0.0.1:5173
```

Vite hace proxy de `/advisor`, `/admin` y `/api` a:

```text
http://127.0.0.1:8000
```

Así la cookie de sesión funciona sin CORS.

## Build

```powershell
cd admin-web
pnpm build
```

Genera `admin-web/dist`.

Para servirla desde el API:

```powershell
pnpm build:console
```

Queda en:

```text
http://127.0.0.1:8000/console/
```

## Rutas

| Ruta | Función |
|---|---|
| `/login` | Ingreso de asesor |
| `/inbox` | Bandeja de handoffs |
| `/agents` | Administración de agentes (solo admin) |
| `/metrics` | Métricas de atención (admin/supervisor) |

## Funciones

- Login/logout con cookie.
- Login con mostrar/ocultar contraseña, bloqueo de envío y mensaje de error accesible.
- Logout redirige a `/console/login`, no a la página heredada.
- Cookie `Secure` automática cuando la consola se sirve por HTTPS.
- Bandeja con handoffs abiertos.
- Filtros: todos, pendientes, tomados, SLA.
- Búsqueda por nombre, número o motivo.
- Toasts y notificaciones del navegador.
- Badge de pendientes.
- Guardia visible.
- Inbox de tres paneles en escritorio: lista, conversación y contexto.
- Contexto del cliente en `Drawer` en tablet/móvil.
- Composer dentro del panel de conversación, sin desplazarse con la página.
- Detalle con conversación, carrito y pedidos.
- Tomar, responder y resolver.
- Composer con Enter para enviar, Shift+Enter para salto.
- Plantillas rápidas.
- Notas internas.
- Adjuntos salientes: imágenes y documentos.
- Adjuntos entrantes: previsualización de imágenes y descarga de documentos.
- Errores de envío visibles.
- Administración de agentes: crear, activar, guardia, admin.
- Tiempo real por SSE (`/advisor/events`), con respaldo cada 30 s.
- Estado leído/no leído por asesor.
- En móvil, al elegir un caso la consola hace scroll al panel de conversación.
- Navegación interna con `Link` para respetar `base=/console/`.
- Command palette con `Ctrl+K` para ir a Bandeja, Agentes, Métricas o cerrar sesión.
- Modo oscuro/claro desde la topbar, con preferencia persistida por Mantine.
- Lista de handoffs con scroll propio y contador en el encabezado del panel.
- Contexto del cliente en panel lateral con scroll independiente.

## Layout

La consola usa `AppShell` de Mantine:

- topbar con marca, usuario y logout,
- sidebar con Bandeja, Agentes y Métricas según rol,
- navegación responsive con burger en móvil,
- contenido dentro de `AppShell.Main`.

El inbox usa tres columnas en escritorio:

```text
lista (360px) | conversación (flexible) | contexto (300px)
```

En pantallas menores el contexto se abre en un `Drawer`.

La lógica de bandeja, handoffs y conversación sigue en los componentes React
existentes.

## Identidad visual

Paleta:

- rojo para acciones y alertas,
- azul para enlaces y estados secundarios,
- negro para cabecera y texto,
- blanco para superficies.

## Producción

Opciones:

1. Servir `dist/` con Nginx/Caddy y proxy `/advisor`, `/admin` y `/api` al API.
2. Servir desde el mismo dominio que FastAPI.
3. Mantener Vite solo para desarrollo.

No usar el dev server de Vite en producción.
