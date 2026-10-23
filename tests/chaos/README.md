# Pruebas de caos del bot

Suite automatizada con SQLite en memoria. No toca WhatsApp, VTEX ni la base real.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\chaos -q
```

## Qué cubre

- respuesta vacía / fallback,
- pregunta pendiente de medida,
- referencia “el primero”,
- detector de bucles,
- stock suficiente para la cantidad,
- stock insuficiente,
- prioridad de marca por regla,
- falla simulada del LLM,
- respuestas sin mostrar stock.

## Agregar escenarios

1. Crear productos de prueba con un SKU/categoría única.
2. Crear contacto y conversación con `_contact()`.
3. Preparar el estado, reglas o recomendación.
4. Ejecutar `Agent.handle()` o `Toolbox`.
5. Verificar propiedades:
   - no vacío,
   - no stock,
   - regla aplicada,
   - sin bucle,
   - derivación/fallback.

Las pruebas no deben depender de texto exacto del LLM. Verifican comportamiento y datos.
