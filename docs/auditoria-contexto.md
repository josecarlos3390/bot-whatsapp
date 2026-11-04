# Auditoría: el contexto contra el mensaje nuevo

Los bugs de esta semana tuvieron una sola causa:

> **El estado de la conversación pesaba más que lo que el cliente acababa de
> escribir.**

| Bug real | Qué ganó |
|---|---|
| «otra opción» buscó el texto literal | No se reconoció el intent |
| «el auto a escala» abrió la ficha del estuche | `last_query` / último producto |
| «autos a escala» mostró muñecas | respuesta corta + `last_query` |
| «tienes muñecas?» dijo que no tenía | la ñ al comparar |
| «mostrame hot wheels» dijo «no tengo» | comparación de nombres |

## Regla

> **El mensaje nuevo gana.** El contexto solo completa cuando el mensaje no
> alcanza.

## Inventario de lugares donde entra el contexto

| # | Lugar | Qué hace | Estado |
|---|---|---|---|
| 1 | `tool_search_products` · `state.category` / `state.brand` | aplica el rubro y la marca de la charla | ✅ ahora se ignora si el mensaje encuentra algo solo |
| 2 | `handle` · respuesta corta (1-4 palabras) | pega el mensaje a `last_query` | ✅ solo si el mensaje no encuentra nada solo |
| 3 | `_search_reply` · reescritura por IA | puede cambiar la consulta | ✅ no puede borrar palabras del cliente |
| 4 | `_direct_reply_for_tool` · ficha | abre un SKU elegido por el modelo | ✅ se descarta si el nombre no contiene las palabras del mensaje |
| 5 | `_resolve_pending` | usa la ranura pendiente (medida, presupuesto) | ✅ si el mensaje es otra búsqueda o pregunta, se limpia |
| 6 | `_resolve_reference` | «ese», «el segundo» | ✅ solo con demostrativos u ordinales |
| 7 | `more` / «ver más» | reusa `last_query` | ✅ a propósito, con paginación |
| 8 | `preferences.enrich` | agrega la medida de colchón recordada | ✅ solo si habla de cama/colchón |
| 9 | `price_reply` («más baratos») | usa `last_query` como base | ✅ a propósito: es relativo al rubro |
| 10 | `most_chosen` | ranking por rubro previo | ✅ a propósito |
| 11 | `repeat_guard` / `coherence` | evita repetir listados | ⚠️ puede tapar una respuesta pedida; las acciones están exceptuadas |
| 12 | `clarify.py` | interpreta respuestas sueltas | ✅ con `last_query` como pista |

## Qué se corrigió en esta auditoría

1. **`state.category` / `state.brand`**: se aplican solo si el mensaje no
   encuentra productos por sí mismo. Antes, «autos a escala» heredaba el rubro
   «muñecas».
2. **Respuesta corta**: se combina con la búsqueda anterior solo si el mensaje
   no encuentra nada. Si encuentra («a fricción»), se lista en el acto.
3. **Preguntas sobre la propia conducta**: «primero me dijiste 5 y luego 3»,
   «no son los autos que pedí» ahora se reconocen y se contestan con una
   disculpa y opciones, en vez de abrir la ficha de un producto.
4. **`kidsage:`** quedó registrada como acción (antes caía en la búsqueda).

## Riesgos que quedan

| Riesgo | Por qué | Mitigación |
|---|---|---|
| `repeat_guard` tapando una respuesta | compara listados anteriores | las acciones ya están exceptuadas; revisar si aparece en un chat |
| Coherencia por rubro demasiado estricta | puede descartar productos válidos | `auditar_coherencia` lo detecta si genera «no tengo» |
| La IA reescribe la consulta | cambia el significado | regla de «no perder palabras» |
| Ranuras pendientes viejas | piden medida cuando el cliente cambió de tema | se limpian al detectar otra búsqueda o pregunta |

## Cómo se vigila

```powershell
# Rejuega mensajes reales y marca incoherencias
.\.venv\Scripts\python.exe -m scripts.auditar_coherencia --dias 7

# Regresión de los bugs que ya aparecieron
.\.venv\Scripts\python.exe -m pytest tests/test_coherencia_respuestas.py -q
```

**Cada bug nuevo que aparezca en un chat real se agrega primero como test.**
