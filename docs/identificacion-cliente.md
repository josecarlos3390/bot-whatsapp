# Identificación y onboarding del cliente

**Pregunta:** ¿el bot ya responde primero y luego pregunta si el cliente compró
antes en ROHO, o le pide el carnet para personalizar?

**Respuesta corta:** sí. El flujo ya está implementado: responde primero, ofrece
identificarse solo cuando va a recomendar o comprar, busca por carnet/NIT en
SAP, confirma el nombre y vincula el historial. El documento se redacta de los
mensajes guardados.

---

## 1. Qué hace hoy

| Comportamiento | Estado |
|---|---|
| Responde primero lo que pregunta | Sí |
| Usa memoria si ya conoce al cliente | Sí: perfil, hechos, resumen e historial |
| Pregunta “¿ya compraste antes en ROHO?” | Sí, cuando la conversación va a recomendación/compra |
| Pide carnet/NIT | Sí, después de dar valor y con consentimiento |
| Busca compras por carnet/NIT | Sí: `identify_customer` consulta `FederalTaxID` |
| Confirma nombre antes de vincular | Sí |
| Vincula `CardCode` y sincroniza compras | Sí: `link_customer` |
| Redacta el documento de los mensajes | Sí: queda `[documento]` |
| Recomienda según compras | Sí, si el contacto ya está vinculado |

---

## 2. Por qué se pide después y no al inicio

- Es un dato personal sensible.
- El mensaje del cliente se guarda en `messages`; por eso el documento se
  **redacta** después de la consulta y solo queda el vínculo `contact_id → CardCode`.
- En SAP QA, `VTX000019` tiene `FederalTaxID=331596028`, pero **3 clientes**
  comparten ese valor; por eso se muestran candidatos y se confirma el nombre.
- El carnet no es lo mismo que el RUT/NIT; `FederalTaxID` puede ser ambos.
- Pedirlo antes de dar valor aumenta el abandono.

**Regla:** primero responder y dar valor; identificar solo cuando haga falta
(historial, recomendación personalizada o factura).

---

## 3. Flujo recomendado

```text
Cliente: "Busco un regalo"
Bot:     responde con 2 opciones y pregunta ocasión/presupuesto
         ↓
Bot: "¿Ya compraste antes en ROHO?"
         ├─ No → 2 preguntas de preferencia; perfil básico; sin carnet
         └─ Sí → "¿Me pasás el carnet o el teléfono con el que compraste?"
                    ↓
              buscar cliente en SAP
                    ↓
              ¿coincide nombre? → vincular CardCode → historial
                    ↓
              recomendar / cerrar
```

Para una compra, el carnet solo se pide si la factura lo exige, no para mirar
precios.

---

## 4. Qué se implementó y qué falta

**Implementado:**

- `identify_customer(document, consent)` → busca por `FederalTaxID`.
- `link_customer(card_code, consent)` → valida candidato, vincula y sincroniza compras.
- Candidatos con expiración de 15 minutos para evitar vinculaciones inventadas.
- Redacción de `[documento]` en los mensajes guardados.
- Prompt de onboarding: responder → valor → preguntar si compró antes → carnet/NIT opcional.

**Pendiente:**

- Rate limiting para evitar enumeración de carnets.
- Cifrado si se decide almacenar el documento (hoy no se almacena).
- Segmentos y campañas.
- Verificación adicional (OTP) para casos sensibles.

### Identificador

Definir con el negocio:

1. ¿El carnet está guardado en SAP? ¿En `FederalTaxID`, en un UDF o no está?
2. ¿Es único? En QA no lo es.
3. ¿Se puede usar teléfono + nombre + última compra?
4. ¿Se exige carnet para factura?

### Privacidad

- Consentimiento explícito antes de buscar.
- No guardar el carnet en `messages`; redactarlo antes de persistir.
- Guardar solo el vínculo `contact_id → sap_card_code`, no el documento.
- Cifrado en reposo si se almacena.
- Retención y borrado.
- Rate limiting para evitar enumeración de carnet.

### Herramientas

```text
identify_customer(document | phone, consent=true)
  → candidatos: CardCode, nombre enmascarado
verify_customer(card_code, nombre)
  → vincula contacto y dispara sync de compras
link_customer(card_code)
```

Nunca vincular automáticamente si hay más de un candidato.

### Prompt

- Responder primero.
- No pedir carnet para consultas simples.
- Preguntar “¿ya compraste antes en ROHO?” solo si la conversación va hacia
  recomendación personalizada o compra.
- Explicar el beneficio y pedir permiso.
- Si el cliente no quiere dar datos, seguir con preguntas de preferencia.

---

## 5. Ejemplo de conversación

> **Cliente:** “Busco algo para regalar.”
>
> **Bot:** “Para regalo tengo la maceta Husik a Bs 1.270 (50% off) y el joyero
> Concepts a Bs 10,70. ¿Es para hombre o mujer?”
>
> **Cliente:** “Para mujer.”
>
> **Bot:** “¿Ya compraste antes en ROHO? Si me decís que sí, con tu carnet o el
> teléfono de tu compra veo tu historial y te recomiendo algo más afinado.”
>
> **Cliente:** “Sí, pero no quiero dar carnet.”
>
> **Bot:** “Sin problema. ¿Preferís algo decorativo o práctico? Con eso te guío.”

---

## 6. Recomendación

No pedir carnet “al iniciar” por defecto. Implementar primero:

1. **Vinculación por teléfono + nombre + última compra**.
2. **Carnet opcional** solo para factura o historial, con consentimiento,
   redacción y verificación.
3. **Onboarding comercial**: responder → dar valor → preguntar si compró antes →
   ofrecer identificación → recomendar.

Eso mejora la conversión sin convertir el chat en un formulario.
