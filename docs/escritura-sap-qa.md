# Prueba de escritura en SAP QA (19-oct-2026)

Objetivo: validar `Orders`, `Invoices` e `IncomingPayments` contra
`RETAIL_QA` con el usuario `jdiaz`.

## Resultado

| Paso | Resultado |
|---|---|
| Login Service Layer | OK |
| Alta de socio `WA59170000099` | **OK** (con `FederalTaxID`) |
| `POST /Orders` | **OK** — DocEntry 1089, 1091, 1093 |
| `POST /Invoices` (desde pedido) | **Bloqueado** por autorización de almacén |
| `POST /IncomingPayments` | No ejecutado |
| Limpieza | Pedidos 1089, 1091 y 1093 cancelados (`204`) |

Error de factura:

```text
-1116 (16) El usuario actual no se encuentra autorizado para trabajar
con este(os) almacén(es).
```

El pedido se crea, pero la factura exige autorización de almacén para el usuario
de integración. No es un problema del payload: se probó con `101-1001` y
`103-1001`, y con `WarehouseCode` explícito.

## Campos que exige esta instalación

La empresa QA usa localización chilena. Para crear documentos:

| Campo | Ejemplo | Dónde |
|---|---|---|
| `FederalTaxID` | `99999999` (prueba) | Alta de `BusinessPartners`; es el RUT |
| `CostingCode` | `14304` | Línea de pedido/factura |
| `CostingCode2` | `ECO` | Línea |
| `CostingCode3` | `1000` | Línea |
| `TaxCode` | `IVA` | Línea; sin esto: “Row without tax” |
| `WarehouseCode` | `101-1001` / `103-1001` | Línea |

`FederalTaxID` es obligatorio para dar de alta al socio. En producción hay que
pedir RUT/NIT al cliente o usar un socio genérico “Consumidor Final”.

## Configuración usada

```env
SAP_MODE=service_layer
SAP_LIVE_READS=true
SAP_WRITE_ENABLED=false
SAP_WAREHOUSE=101-1001
SAP_PRICE_LIST=1
SAP_COSTING_CODE=14304
SAP_COSTING_CODE2=ECO
SAP_COSTING_CODE3=1000
SAP_TAX_CODE=IVA
```

## Qué falta para completar la escritura

1. **Autorizar al usuario** en SAP B1:
   - Administración → Configuración → General → Usuarios → `jdiaz` (o el usuario
     de integración) → Autorizaciones → Almacenes.
   - Habilitar los almacenes de venta (`101-1001`, `103-1001` o el que defina el
     negocio) y los permisos de **A/R Invoice**.
2. Confirmar con contabilidad:
   - almacén de despacho online,
   - centro de costo (`14304/ECO/1000`),
   - código de impuesto (`IVA`) y si el precio incluye impuesto.
3. Repetir la prueba: pedido → factura → `IncomingPayments`.
4. Definir la cuenta de caja/banco (`CashAccount`) o método de pago para el cobro.

Mientras esto no esté resuelto, `SAP_WRITE_ENABLED=false` evita crear pedidos
parciales que luego no se pueden facturar.
