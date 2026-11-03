# Pruebas del bot

## Qué se corre antes de publicar

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.auditoria_dialogos --generados
.\.venv\Scripts\python.exe -m scripts.prueba_flujos_reales
.\.venv\Scripts\python.exe -m scripts.auditar_coherencia --dias 7
```

Resultado esperado hoy: **734 tests**, auditoría 26/26, flujos 16/16,
coherencia sin hallazgos.

## Auditoría de coherencia

`scripts/auditar_coherencia.py` toma los mensajes reales de los clientes y los
vuelve a pasar por el bot. Marca:

| Hallazgo | Qué significa |
|---|---|
| `niega_tenencia` | El bot dice «no tengo X» y el catálogo sí tiene X |
| `ficha_ajena` | Abre la ficha de un producto que no tiene que ver con el pedido |
| `pregunta_sin_productos` | Pregunta en vez de mostrar, cuando había algo para mostrar |
| `sin_respuesta` | No contestó |

```powershell
python -m scripts.auditar_coherencia
python -m scripts.auditar_coherencia --dias 30 --limite 100
```

## Regresión de bugs reales

`tests/test_coherencia_respuestas.py` fija los casos que ya fallaron en
producción:

- «tienes muñecas?» respondido con «no tengo» (la ñ).
- «busco hot wheels» con «no tengo hot wheels exactamente».
- «quiero el auto a escala» abriendo la ficha de un estuche.
- «Muéstrame el menú de opciones» respondido con «no tengo un menú».

**Regla:** cada bug que aparezca en un chat real se agrega a ese archivo
**antes** de corregirlo, para que no vuelva.

## De dónde salen los bugs

Todos los de esta semana compartieron una causa: **el contexto de la charla
pesaba más que el mensaje nuevo**.

| Bug | Contexto que ganó |
|---|---|
| «otra opción» buscó el texto literal | No se usó el menú |
| «el auto a escala» abrió el estuche | El último producto visto |
| «tienes muñecas?» dijo que no tenía | La ñ del catálogo |
| «mostrar hot wheels» dijo «no tengo» | El comparador de nombres |

Los tres chequeos de `services/coherencia.py` cubren esas tres últimas
familias.
