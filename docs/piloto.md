# Piloto con clientes reales

Guía para operar el bot durante las primeras 2–3 semanas, medir y decidir.

## Objetivo

Comprobar con tráfico real que el bot **resuelve, deriva bien y no inventa**,
antes de migrar al número productivo y activar el catálogo nativo.

## Alcance

- 20 a 50 clientes.
- Conversaciones de servicio (las que inicia el cliente).
- Un asesor de guardia por franja.

## Duración

2 a 3 semanas, o hasta juntar 200 conversaciones.

## Qué hace el bot cada día solo

| Automático | Dónde se ve |
|---|---|
| Informe del día | Panel → Operación → **Piloto · últimas 24 h** |
| Fuzzing nocturno | `logs/fuzz-history.json`; aviso en `logs/fuzz-alert.txt` |
| Casos escalados por demora | Panel → bandeja, filtro **En cola** |
| Aprendizaje pendiente | Panel → Operación → **Pendientes de revisión** |

## Rutina diaria (10 minutos)

1. Abrir el panel y mirar **Piloto**.
2. Revisar "El bot no resolvió": si algo se repite, cargarlo al catálogo o a
   las políticas.
3. Aprobar o descartar el aprendizaje pendiente.
4. Mirar la bandeja: casos en cola y escalados.

## Rutina semanal (30 minutos)

1. Leer el informe de **Calidad del catálogo** y pasar el listado a ecommerce.
2. Revisar **KPIs de asesores**: SLA, primera respuesta, satisfacción.
3. Correr el informe de títulos y actualizar los productos de la campaña.

## Qué medir

| Indicador | Objetivo | Dónde |
|---|---|---|
| Conversaciones atendidas sin derivar | ≥ 60 % | Panel → Piloto |
| Casos en cola al cierre del día | 0 | Panel → bandeja |
| Respuestas incoherentes | 0 o muy pocas | Panel → Piloto |
| Primera respuesta del asesor | < 5 min | Panel → Agentes |
| Satisfacción | ≥ 4/5 | Panel → Agentes |
| Búsquedas sin resultado | < 20 % de los mensajes | Panel → Piloto |

## Criterio para avanzar a la etapa siguiente

Se migra al número productivo cuando se cumplan **6 de 8** criterios del
semáforo (Panel → Operación → Preparación para producción) y además:

- Dos semanas con 0 respuestas incoherentes.
- Ningún caso quedó sin respuesta más de 15 minutos.
- Al menos un asesor usó el panel todos los días.

## Qué hacer si algo falla

| Síntoma | Acción |
|---|---|
| El bot inventa disponibilidad | Revisar el catálogo de ese rubro; el guard solo niega si no hay nada |
| Respuesta sin sentido | Mirar el contador de incoherentes y el último texto fijo tocado |
| Casos en cola acumulados | Ver presencia: asesores desconectados o tope bajo |
| Cliente enojado | La derivación se dispara sola; revisar el historial del caso |
| Calidad en baja | Ver `fuzz-alert.txt` y comparar con la corrida anterior |

## Registro

Cada día queda un archivo `logs/piloto-AAAA-MM-DD.md` con los números.
Es la evidencia para decidir la migración.
