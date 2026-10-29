"""Conectores con SAP Business One.

Dos implementaciones detrás de la misma interfaz:

* ``MockSap``: usa el catálogo local. Sirve para desarrollar sin SAP.
* ``ServiceLayerSap``: llama al Service Layer real (OData REST).

En producción se cambia con ``SAP_MODE=service_layer``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import CatalogItem, Contact, Order

logger = logging.getLogger(__name__)


class SapError(RuntimeError):
    pass


class SapNotFound(SapError):
    pass


@dataclass
class SapItem:
    sku: str
    name: str
    price: Decimal
    stock: int
    currency: str = "BOB"
    stock_by_store: dict[str, int] = field(default_factory=dict)
    # VTEX exposes list/base price and selling price separately. SAP leaves
    # this as None and keeps using price as the base.
    list_price: Decimal | None = None
    image_url: str | None = None
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    barcode: str | None = None


@dataclass
class QuantityTier:
    quantity: int
    price: Decimal
    discount_percent: Decimal = Decimal("0")


@dataclass
class PricePeriod:
    valid_from: date | None
    valid_to: date | None
    price: Decimal | None
    discount_percent: Decimal = Decimal("0")
    price_list: int = 1
    tiers: list[QuantityTier] = field(default_factory=list)


@dataclass
class Offer:
    sku: str
    name: str
    quantity: int
    base_price: Decimal
    final_price: Decimal
    discount_percent: Decimal
    currency: str
    stock_by_store: dict[str, int]
    period_from: date | None = None
    period_to: date | None = None
    tier_quantity: int | None = None
    tiers: list[QuantityTier] = field(default_factory=list)
    image_url: str | None = None
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    barcode: str | None = None

    def as_dict(self) -> dict:
        base = Decimal(self.base_price)
        final = Decimal(self.final_price)
        raw_discount = Decimal(self.discount_percent or 0)
        if raw_discount < 0:
            raw_discount = Decimal("0")
        if final > base:
            price_note = (
                f"Precio de lista Bs {base}; precio especial vigente "
                f"Bs {final} (no es un descuento)."
            )
        elif raw_discount > 0:
            price_note = (
                f"Precio de lista Bs {base}; precio con descuento "
                f"Bs {final}."
            )
        else:
            price_note = f"Precio de lista Bs {base}."
        return {
            "sku": self.sku,
            "name": self.name,
            "quantity": self.quantity,
            "base_price": str(self.base_price),
            "final_price": str(self.final_price),
            "discount_percent": str(raw_discount),
            "is_promotion": raw_discount > 0,
            "is_special_price": final != base,
            "price_note": price_note,
            "currency": self.currency,
            "stock_by_store": self.stock_by_store,
            "image_url": self.image_url,
            "description": self.description,
            "brand": self.brand,
            "category": self.category,
            "barcode": self.barcode,
            "period_from": self.period_from.isoformat() if self.period_from else None,
            "period_to": (
                self.period_to.isoformat()
                if self.period_to and self.period_to.year < 2099
                else None
            ),
            "tier_quantity": self.tier_quantity,
            "tiers": [
                {
                    "quantity": tier.quantity,
                    "price": str(tier.price),
                    "discount_percent": str(tier.discount_percent),
                }
                for tier in self.tiers
            ],
        }


@dataclass
class SapOrderResult:
    doc_entry: int
    doc_num: int
    total: Decimal


@dataclass
class SapInvoiceResult:
    doc_entry: int
    doc_num: int
    total: Decimal


@dataclass
class SapPaymentResult:
    doc_entry: int
    doc_num: int


class SapAdapter(Protocol):
    async def get_item(
        self, sku: str, force_refresh: bool = False
    ) -> SapItem | None: ...

    async def search_items(
        self, query: str, limit: int = 8
    ) -> list[dict]: ...

    async def get_offer(
        self, sku: str, quantity: int = 1, force_refresh: bool = False
    ) -> Offer | None: ...

    async def create_sales_order(self, order: Order) -> SapOrderResult: ...

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult: ...

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult: ...


def _doc_base(order: Order) -> int:
    """Número estable y positivo a partir del UUID, sólo para el mock."""
    return int(uuid.UUID(order.id).int % 90000) + 1000


def _as_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def build_offer(
    item: SapItem, periods: list[PricePeriod], quantity: int = 1
) -> Offer:
    """Aplica período vigente y escalón por cantidad (precio unitario)."""
    quantity = max(int(quantity), 1)
    today = date.today()
    active = [
        period
        for period in periods
        if (period.valid_from is None or period.valid_from <= today)
        and (period.valid_to is None or today <= period.valid_to)
    ]
    period = max(
        active, key=lambda p: p.valid_from or date.min
    ) if active else None

    final_price = Decimal(item.price)
    base_price = (
        Decimal(item.list_price)
        if item.list_price is not None and item.list_price > 0
        else Decimal(item.price)
    )
    tier: QuantityTier | None = None
    active_tiers: list[QuantityTier] = []
    if period is not None:
        active_tiers = sorted(
            [t for t in period.tiers if t.price > 0],
            key=lambda t: t.quantity,
        )
        if period.price is not None and period.price > 0:
            final_price = Decimal(period.price)
        # SAP SpecialPriceQuantityAreas describes exact quantities (for
        # example 3 units at one price, 4 at another). Do not treat it as
        # "from X units".
        tier = next(
            (t for t in active_tiers if t.quantity == quantity),
            None,
        )
        if tier is not None:
            final_price = Decimal(tier.price)

    discount = Decimal("0")
    if base_price > 0:
        discount = ((base_price - final_price) / base_price) * 100
        discount = discount.quantize(Decimal("0.01"))

    return Offer(
        sku=item.sku,
        name=item.name,
        quantity=quantity,
        base_price=base_price,
        final_price=final_price,
        discount_percent=discount,
        currency=item.currency,
        stock_by_store=item.stock_by_store,
        period_from=period.valid_from if period else None,
        period_to=period.valid_to if period else None,
        tier_quantity=tier.quantity if tier else None,
        tiers=active_tiers,
        image_url=item.image_url,
        description=item.description,
        brand=item.brand,
        category=item.category,
        barcode=item.barcode,
    )


class MockSap:
    """Implementación de desarrollo: no toca SAP, pero respeta el contrato."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_item(self, sku: str, force_refresh: bool = False) -> SapItem | None:
        row = await self.session.scalar(
            select(CatalogItem).where(CatalogItem.sku == sku, CatalogItem.active.is_(True))
        )
        if row is None:
            return None
        return SapItem(
            sku=row.sku,
            name=row.name,
            price=Decimal(row.price),
            stock=row.stock,
            currency=row.currency,
            stock_by_store={settings.sap_warehouse: row.stock},
        )

    async def search_items(self, query: str, limit: int = 8) -> list[dict]:
        # El mock no tiene catálogo remoto: la búsqueda local ya cubre el caso.
        return []

    async def get_offer(
        self, sku: str, quantity: int = 1, force_refresh: bool = False
    ) -> Offer | None:
        item = await self.get_item(sku)
        if item is None:
            return None
        return build_offer(item, [], quantity)

    async def create_sales_order(self, order: Order) -> SapOrderResult:
        base = _doc_base(order)
        logger.info("MOCK SAP: pedido %s creado como DocEntry=%s", order.number, base)
        return SapOrderResult(
            doc_entry=base, doc_num=base + 10000, total=Decimal(order.total)
        )

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult:
        base = (order.sap_doc_entry or _doc_base(order)) + 1000
        logger.info("MOCK SAP: factura del pedido %s como DocEntry=%s", order.number, base)
        return SapInvoiceResult(
            doc_entry=base, doc_num=base + 10000, total=Decimal(order.total)
        )

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult:
        base = invoice.doc_entry + 1000
        logger.info(
            "MOCK SAP: pago aplicado a factura %s como DocEntry=%s",
            invoice.doc_entry,
            base,
        )
        return SapPaymentResult(doc_entry=base, doc_num=base + 10000)


class ServiceLayerSap:
    """Cliente mínimo del Service Layer de SAP Business One 10."""

    def __init__(self, session: AsyncSession) -> None:
        if not settings.sap_sl_url:
            raise SapError("SAP_SL_URL no está configurado")
        self.session = session
        self._client = httpx.AsyncClient(
            base_url=settings.sap_sl_url.rstrip("/") + "/",
            timeout=25.0,
            verify=settings.sap_verify_tls,
        )
        self._login_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def warmup(self) -> None:
        """Abre sesión antes del primer usuario para no pagar el login."""
        await self._login()
        await self._request("GET", "Items", params={"$top": 1, "$select": "ItemCode"})

    async def _login(self) -> None:
        async with self._login_lock:
            response = await self._client.post(
                "Login",
                json={
                    "CompanyDB": settings.sap_company_db,
                    "UserName": settings.sap_user,
                    "Password": settings.sap_password,
                },
            )
            if response.status_code >= 400:
                raise SapError(
                    f"Login SAP falló ({response.status_code}): {response.text[:300]}"
                )
            # En algunas instalaciones (detrás de un proxy) el Service Layer no
            # devuelve la cookie B1SESSION: el identificador viene en el body.
            session_id = (response.json() or {}).get("SessionId")
            if session_id:
                self._client.cookies.set("B1SESSION", session_id)
            # Si la instalación sí devuelve B1SESSION/ROUTEID, httpx los conserva.

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        path = path.lstrip("/")
        if not self._client.cookies:
            await self._login()
        response = await self._client.request(method, path, **kwargs)
        if response.status_code == 401:
            await self._login()
            response = await self._client.request(method, path, **kwargs)
        if response.status_code == 404:
            raise SapNotFound(f"SAP {method} {path}: no encontrado")
        if response.status_code >= 400:
            raise SapError(
                f"SAP {method} {path} -> {response.status_code}: {response.text[:500]}"
            )
        return response

    async def get(self, path: str, params: dict | None = None) -> dict:
        """Lectura genérica para el sincronizador de catálogo."""
        response = await self._request("GET", path, params=params)
        return response.json()

    async def get_item(self, sku: str, force_refresh: bool = False) -> SapItem | None:
        try:
            response = await self._request(
                "GET",
                f"/Items('{sku}')",
                params={
                    "$select": (
                        "ItemCode,ItemName,QuantityOnStock,"
                        "ItemPrices,ItemWarehouseInfoCollection"
                    )
                },
            )
        except SapNotFound:
            return None
        data = response.json()
        price = Decimal("0")
        for entry in data.get("ItemPrices", []):
            if entry.get("PriceList") == settings.sap_price_list:
                price = Decimal(str(entry.get("Price", 0)))
                break
        else:
            prices = data.get("ItemPrices") or []
            if prices:
                price = Decimal(str(prices[0].get("Price", 0)))

        stock_by_store: dict[str, int] = {}
        for warehouse in data.get("ItemWarehouseInfoCollection", []):
            code = warehouse.get("WarehouseCode")
            if code not in settings.sap_store_map:
                continue
            in_stock = Decimal(str(warehouse.get("InStock") or 0))
            committed = Decimal(str(warehouse.get("Committed") or 0))
            available = warehouse.get("Available")
            stock_by_store[code] = int(
                available if available is not None else in_stock - committed
            )

        stock = stock_by_store.get(settings.sap_warehouse)
        if stock is None:
            stock = int(data.get("QuantityOnStock") or 0)

        return SapItem(
            sku=data["ItemCode"],
            name=data.get("ItemName") or data["ItemCode"],
            price=price,
            stock=stock,
            stock_by_store=stock_by_store,
        )

    async def search_items(self, query: str, limit: int = 8) -> list[dict]:
        """Búsqueda por nombre en el Service Layer (sensible a mayúsculas)."""
        term = (query or "").strip()
        if not term:
            return []
        for candidate in (term.upper(), term):
            safe = candidate.replace("'", "''")
            response = await self._request(
                "GET",
                "/Items",
                params={
                    "$select": "ItemCode,ItemName,QuantityOnStock,ItemPrices",
                    "$top": max(1, min(int(limit), 25)),
                    "$filter": (
                        f"contains(ItemName,'{safe}') and Valid eq 'tYES' "
                        "and SalesItem eq 'tYES'"
                    ),
                },
            )
            rows = response.json().get("value") or []
            if rows:
                return [self._search_row(row) for row in rows]
        return []

    @staticmethod
    def _search_row(row: dict) -> dict:
        price = Decimal("0")
        prices = row.get("ItemPrices") or []
        for entry in prices:
            if entry.get("PriceList") == settings.sap_price_list:
                price = Decimal(str(entry.get("Price", 0)))
                break
        else:
            if prices:
                price = Decimal(str(prices[0].get("Price", 0)))
        return {
            "sku": row.get("ItemCode"),
            "name": row.get("ItemName"),
            "price": float(price),
            "stock": int(Decimal(str(row.get("QuantityOnStock") or 0))),
            "currency": "BOB",
        }

    async def get_price_periods(
        self, sku: str, force_refresh: bool = False
    ) -> list[PricePeriod]:
        """Precios especiales por período/cantidad para un SKU.

        Se consulta sólo al abrir ficha/agregar; no se sincronizan los 83k
        registros de SpecialPrices.
        """
        key = sku.strip().upper()
        cached = _PRICE_CACHE.get(key)
        if (
            not force_refresh
            and cached
            and time.monotonic() - cached[0]
            < settings.sap_price_cache_ttl_seconds
        ):
            return cached[1]

        lock = _PRICE_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            cached = _PRICE_CACHE.get(key)
            if (
                not force_refresh
                and cached
                and time.monotonic() - cached[0]
                < settings.sap_price_cache_ttl_seconds
            ):
                return cached[1]
            try:
                escaped = sku.replace("'", "''")
                data = await self.get(
                    "SpecialPrices",
                    params={
                        "$filter": f"ItemCode eq '{escaped}'",
                        "$select": (
                            "ItemCode,CardCode,Price,PriceListNum,"
                            "DiscountPercent,SpecialPriceDataAreas"
                        ),
                        "$top": 50,
                    },
                )
                periods: list[PricePeriod] = []
                for row in data.get("value", []):
                    if row.get("CardCode") not in ("*1", "*"):
                        continue
                    for area in row.get("SpecialPriceDataAreas") or []:
                        price_list = int(
                            area.get("PriceListNo")
                            or row.get("PriceListNum")
                            or settings.sap_price_list
                        )
                        if price_list != settings.sap_price_list:
                            continue
                        special = Decimal(str(area.get("SpecialPrice") or 0))
                        tiers = []
                        for tier in area.get("SpecialPriceQuantityAreas") or []:
                            qty = int(tier.get("Quantity") or 0)
                            tier_price = Decimal(
                                str(tier.get("SpecialPrice") or 0)
                            )
                            if qty > 0 and tier_price > 0:
                                tiers.append(
                                    QuantityTier(
                                        quantity=qty,
                                        price=tier_price,
                                        discount_percent=Decimal(
                                            str(tier.get("Discountin") or 0)
                                        ),
                                    )
                                )
                        if special <= 0 and not tiers:
                            continue
                        periods.append(
                            PricePeriod(
                                valid_from=_as_date(area.get("DateFrom")),
                                valid_to=_as_date(area.get("Dateto")),
                                price=special if special > 0 else None,
                                discount_percent=Decimal(
                                    str(area.get("Discount") or 0)
                                ),
                                price_list=price_list,
                                tiers=sorted(
                                    tiers, key=lambda t: t.quantity
                                ),
                            )
                        )
            except Exception:  # noqa: BLE001 - no romper la ficha
                logger.exception("No se pudieron leer precios especiales de %s", sku)
                if force_refresh:
                    raise
                periods = cached[1] if cached else []

            _PRICE_CACHE[key] = (time.monotonic(), periods)
            return periods

    async def get_offer(
        self, sku: str, quantity: int = 1, force_refresh: bool = False
    ) -> Offer | None:
        # Artículo y precios son independientes: en paralelo se ahorra un
        # viaje completo a SAP en la primera consulta.
        if not self._client.cookies:
            await self._login()
        item, periods = await asyncio.gather(
            self.get_item(sku, force_refresh=force_refresh),
            self.get_price_periods(sku, force_refresh=force_refresh),
        )
        if item is None:
            return None
        return build_offer(item, periods, quantity)

    async def _ensure_bp(self, contact: Contact) -> str:
        if contact.sap_card_code:
            return contact.sap_card_code
        digits = "".join(ch for ch in contact.phone_e164 if ch.isdigit())
        card_code = ("WA" + digits)[:15]
        # Si ya existe, se reutiliza (no se depende de UDFs que pueden no existir).
        try:
            await self._request("GET", f"/BusinessPartners('{card_code}')")
            contact.sap_card_code = card_code
            return card_code
        except SapNotFound:
            pass

        payload = {
            "CardCode": card_code,
            "CardName": (contact.name or "Cliente WhatsApp")[:100],
            "CardType": "cCustomer",
            "Phone1": contact.phone_e164,
        }
        if contact.tax_id:
            payload["FederalTaxID"] = contact.tax_id
        response = await self._request("POST", "/BusinessPartners", json=payload)
        card_code = response.json().get("CardCode", card_code)
        contact.sap_card_code = card_code
        return card_code

    async def create_sales_order(self, order: Order) -> SapOrderResult:
        contact = await self._client_get_contact(order.contact_id)
        card_code = await self._ensure_bp(contact)
        lines = [
            {
                "ItemCode": item.sku,
                "Quantity": item.quantity,
                "WarehouseCode": item.store_code or settings.sap_warehouse,
            }
            for item in order.items
        ]
        if settings.sap_costing_code:
            for line in lines:
                line["CostingCode"] = settings.sap_costing_code
                if settings.sap_costing_code2:
                    line["CostingCode2"] = settings.sap_costing_code2
                if settings.sap_costing_code3:
                    line["CostingCode3"] = settings.sap_costing_code3
        if settings.sap_tax_code:
            for line in lines:
                line["TaxCode"] = settings.sap_tax_code
        payload = {
            "CardCode": card_code,
            "DocDate": date.today().isoformat(),
            "DocDueDate": date.today().isoformat(),
            "Comments": f"Pedido WhatsApp {order.number}",
            "DocumentLines": lines,
        }
        response = await self._request("POST", "/Orders", json=payload)
        data = response.json()
        return SapOrderResult(
            doc_entry=int(data["DocEntry"]),
            doc_num=int(data["DocNum"]),
            total=Decimal(str(data.get("DocTotal", order.total))),
        )

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult:
        contact = await self._client_get_contact(order.contact_id)
        card_code = await self._ensure_bp(contact)
        lines = [
            {
                "BaseType": 17,  # Sales Order
                "BaseEntry": order.sap_doc_entry,
                "BaseLine": index,
                "Quantity": item.quantity,
                "WarehouseCode": item.store_code or settings.sap_warehouse,
            }
            for index, item in enumerate(order.items)
        ]
        if settings.sap_tax_code:
            for line in lines:
                line["TaxCode"] = settings.sap_tax_code
        payload = {
            "CardCode": card_code,
            "DocDate": date.today().isoformat(),
            "Comments": f"Factura pedido WhatsApp {order.number}",
            "DocumentLines": lines,
        }
        response = await self._request("POST", "/Invoices", json=payload)
        data = response.json()
        return SapInvoiceResult(
            doc_entry=int(data["DocEntry"]),
            doc_num=int(data["DocNum"]),
            total=Decimal(str(data.get("DocTotal", order.total))),
        )

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult:
        contact = await self._client_get_contact(order.contact_id)
        card_code = await self._ensure_bp(contact)
        payload = {
            "CardCode": card_code,
            "DocDate": date.today().isoformat(),
            "PaymentInvoices": [
                {
                    "DocEntry": invoice.doc_entry,
                    "SumApplied": float(invoice.total),
                }
            ],
        }
        if settings.sap_cash_account:
            payload["CashAccount"] = settings.sap_cash_account
        response = await self._request("POST", "/IncomingPayments", json=payload)
        data = response.json()
        return SapPaymentResult(
            doc_entry=int(data["DocEntry"]),
            doc_num=int(data["DocNum"]),
        )

    async def _client_get_contact(self, contact_id: str) -> Contact:
        contact = await self.session.get(Contact, contact_id)
        if contact is None:
            raise SapError(f"No existe el contacto {contact_id}")
        return contact


class HybridSap:
    """Lecturas en vivo con caché corta; escrituras al adaptador indicado.

    Se usa cuando ``SAP_WRITE_ENABLED=false``: el bot consulta precio/stock
    reales, pero el checkout sigue siendo mock.
    """

    def __init__(
        self,
        reader: SapAdapter,
        writer: SapAdapter,
        ttl_seconds: int,
    ):
        self.reader = reader
        self.writer = writer
        self.ttl = max(ttl_seconds, 1)

    async def get_item(
        self, sku: str, force_refresh: bool = False
    ) -> SapItem | None:
        key = sku.strip().upper()
        cached = _CACHE.get(key)
        if cached and not force_refresh and time.monotonic() - cached[0] < self.ttl:
            return cached[1]

        # Single-flight por SKU: evita 20 consultas iguales a SAP.
        lock = _CACHE_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            cached = _CACHE.get(key)
            if cached and not force_refresh and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
            try:
                item = await self.reader.get_item(sku, force_refresh=True)
            except Exception:
                logger.exception("Lectura SAP en vivo falló para %s", sku)
                if force_refresh:
                    raise
                if cached:
                    return cached[1]
                item = await self.writer.get_item(sku)
            if item is not None:
                _CACHE[key] = (time.monotonic(), item)
            return item

    async def search_items(self, query: str, limit: int = 8) -> list[dict]:
        getter = getattr(self.reader, "search_items", None)
        if getter is None:
            return []
        try:
            return await getter(query, limit=limit)
        except Exception:  # noqa: BLE001 - la caché local sigue respondiendo
            logger.exception("Búsqueda en caliente falló para %s", query)
            return []

    async def get_offer(
        self, sku: str, quantity: int = 1, force_refresh: bool = False
    ) -> Offer | None:
        getter = getattr(self.reader, "get_price_periods", None)
        if getter is None:
            item = await self.get_item(sku, force_refresh=force_refresh)
            if item is None:
                return None
            return build_offer(item, [], quantity)

        async def price_periods() -> list[PricePeriod]:
            try:
                return await getter(sku, force_refresh=force_refresh)
            except Exception:  # noqa: BLE001
                if force_refresh:
                    raise
                logger.exception(
                    "No se pudieron leer precios especiales de %s", sku
                )
                return []

        item, periods = await asyncio.gather(
            self.get_item(sku, force_refresh=force_refresh),
            price_periods(),
        )
        if item is None:
            return None
        return build_offer(item, periods, quantity)

    async def create_sales_order(self, order: Order) -> SapOrderResult:
        return await self.writer.create_sales_order(order)

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult:
        return await self.writer.create_invoice_from_order(order)

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult:
        return await self.writer.create_incoming_payment(order, invoice)


_CACHE: dict[str, tuple[float, SapItem]] = {}
_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_PRICE_CACHE: dict[str, tuple[float, list[PricePeriod]]] = {}
_PRICE_LOCKS: dict[str, asyncio.Lock] = {}
_LIVE_READER: ServiceLayerSap | None = None


def _live_reader() -> ServiceLayerSap:
    global _LIVE_READER
    if _LIVE_READER is None:
        _LIVE_READER = ServiceLayerSap(session=None)  # type: ignore[arg-type]
    return _LIVE_READER


async def close_live_reader() -> None:
    global _LIVE_READER
    if _LIVE_READER is not None:
        await _LIVE_READER.close()
        _LIVE_READER = None


async def warmup_live_reader() -> None:
    await _live_reader().warmup()


class PaasSap:
    """Read adapter for integration-paas."""

    _cache: dict[str, tuple[float, SapItem]] = {}
    _cache_ttl = 60.0

    def __init__(self, session: AsyncSession) -> None:
        if not settings.sap_paas_url:
            raise SapError("SAP_PAAS_URL no está configurado")
        self.session = session
        self._base_path = "api/sap"
        self._client = httpx.AsyncClient(
            base_url=settings.sap_paas_url.rstrip("/") + "/",
            timeout=25.0,
            headers={"X-Api-Key": settings.sap_paas_api_key},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict | None = None) -> dict:
        original = path
        if path.startswith("Invoices(") and path.endswith(")"):
            path = f"api/sap/invoices/{path[9:-1]}"
        elif path == "Invoices" and params:
            match = re.search(r"CardCode\s+eq\s+'([^']+)'", str(params.get("$filter") or ""))
            if match:
                path = f"api/sap/customers/{match.group(1)}/purchases"
                params = {
                    "top": params.get("$top", 20),
                    "skip": params.get("$skip", 0),
                }
        elif path.startswith("BusinessPartners('") and path.endswith("')"):
            prefix = "BusinessPartners('"
            path = f"api/sap/business-partners/{path[len(prefix):-2]}"
        else:
            path = path.lstrip("/")
        response = await self._client.get(path, params=params)
        if response.status_code == 404:
            raise SapNotFound(f"PaaS 404: {original}")
        if response.status_code >= 400:
            raise SapError(
                f"PaaS {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    async def get_item(
        self, sku: str, force_refresh: bool = False
    ) -> SapItem | None:
        cached = self._cache.get(sku)
        if not force_refresh and cached is not None:
            age = time.monotonic() - cached[0]
            if age < self._cache_ttl:
                return cached[1]
        try:
            data = await self.get(
                f"{self._base_path}/items/{sku}",
                params={"stores": ",".join(settings.sap_store_map)},
            )
        except SapNotFound:
            return None
        item = SapItem(
            sku=data.get("sku") or data.get("ItemCode") or sku,
            name=data.get("name") or data.get("ItemName") or sku,
            price=Decimal(str(data.get("price") or data.get("Price") or 0)),
            stock=int(data.get("stock") or data.get("QuantityOnStock") or 0),
            currency=data.get("currency") or "BOB",
            stock_by_store={
                str(key): int(value)
                for key, value in (
                    data.get("stock_by_store")
                    or data.get("StockByStore")
                    or {}
                ).items()
            },
            list_price=(
                Decimal(str(data["list_price"]))
                if data.get("list_price") not in (None, "", 0, "0")
                else None
            ),
            image_url=data.get("image_url"),
            description=data.get("description"),
            brand=data.get("brand"),
            category=data.get("category"),
            barcode=data.get("barcode"),
        )
        self._cache[sku] = (time.monotonic(), item)
        return item

    async def search_items(self, query: str, limit: int = 8) -> list[dict]:
        """Búsqueda por nombre a través del integrador (si lo soporta)."""
        term = (query or "").strip()
        if not term:
            return []
        try:
            data = await self.get(
                f"{self._base_path}/items",
                params={"q": term, "limit": max(1, min(int(limit), 25))},
            )
        except SapNotFound:
            return []
        items = data.get("items") or []
        return [
            {
                "sku": item.get("sku"),
                "name": item.get("name"),
                "name_complete": item.get("name_complete") or item.get("name"),
                "description": item.get("description"),
                "brand": item.get("brand"),
                "category": item.get("category"),
                "barcode": item.get("barcode"),
                "image_url": item.get("image_url"),
                "price": float(item.get("price") or 0),
                "stock": int(item.get("stock") or 0),
                "currency": item.get("currency") or "BOB",
            }
            for item in items
            if item.get("sku") and item.get("name")
        ]

    async def export_items(
        self, after: str | None = None, limit: int = 200
    ) -> list[dict]:
        """Página del catálogo exportada por el integrador (keyset por SKU)."""
        params: dict = {"limit": max(1, min(int(limit), 500))}
        if after:
            params["after"] = after
        data = await self.get(f"{self._base_path}/items/export", params=params)
        return data if isinstance(data, list) else []

    async def catalog_reference(self) -> dict:
        """Grupos de artículos y fabricantes para traducir códigos a nombres."""
        data = await self.get(f"{self._base_path}/catalog-reference")
        return {
            "groups": data.get("groups") or [],
            "manufacturers": data.get("manufacturers") or [],
        }

    async def get_price_periods(
        self, sku: str, force_refresh: bool = False
    ) -> list[PricePeriod]:
        try:
            data = await self.get(f"{self._base_path}/items/{sku}/pricing")
        except SapNotFound:
            return []
        periods: list[PricePeriod] = []
        for row in data.get("periods") or []:
            tiers = [
                QuantityTier(
                    quantity=int(tier.get("quantity") or 0),
                    price=Decimal(str(tier.get("price") or 0)),
                    discount_percent=Decimal(
                        str(tier.get("discount_percent") or 0)
                    ),
                )
                for tier in row.get("tiers") or []
                if int(tier.get("quantity") or 0) > 0
                and Decimal(str(tier.get("price") or 0)) > 0
            ]
            price = row.get("price")
            periods.append(
                PricePeriod(
                    valid_from=_as_date(row.get("valid_from")),
                    valid_to=_as_date(row.get("valid_to")),
                    price=Decimal(str(price)) if price is not None else None,
                    discount_percent=Decimal(
                        str(row.get("discount_percent") or 0)
                    ),
                    price_list=int(row.get("price_list") or settings.sap_price_list),
                    tiers=sorted(tiers, key=lambda tier: tier.quantity),
                )
            )
        return periods

    async def get_offer(
        self, sku: str, quantity: int = 1, force_refresh: bool = False
    ) -> Offer | None:
        # Artículo y precios son independientes: en paralelo se ahorra un
        # viaje completo al integrador en la primera consulta.
        item, periods = await asyncio.gather(
            self.get_item(sku, force_refresh=force_refresh),
            self.get_price_periods(sku, force_refresh=force_refresh),
        )
        if item is None:
            return None
        return build_offer(item, periods, quantity)

    async def post(self, path: str, payload: dict) -> dict:
        response = await self._client.post(path.lstrip("/"), json=payload)
        if response.status_code >= 400:
            detail = response.text[:400]
            try:
                body = response.json()
                detail = str(body.get("error") or body.get("Error") or detail)
            except Exception:  # noqa: BLE001 - respuesta no JSON
                pass
            raise SapError(f"PaaS {response.status_code}: {detail}")
        return response.json()

    async def _ensure_bp(self, contact: Contact) -> str:
        """CardCode del cliente: existente, creado con su RUT o genérico."""
        if contact.sap_card_code:
            return contact.sap_card_code
        digits = "".join(ch for ch in contact.phone_e164 if ch.isdigit())
        card_code = ("WA" + digits)[:15]
        if contact.tax_id:
            data = await self.post(
                "api/sap/business-partners",
                {
                    "cardCode": card_code,
                    "cardName": (contact.name or "Cliente WhatsApp")[:100],
                    "phone": contact.phone_e164,
                    "federalTaxId": contact.tax_id,
                },
            )
            card_code = data.get("cardCode") or data.get("CardCode") or card_code
        elif settings.sap_default_card_code.strip():
            card_code = settings.sap_default_card_code.strip()
        else:
            raise SapError(
                "El cliente no está identificado en SAP: falta RUT o CardCode. "
                "Pedile el RUT/NIT o configurá SAP_DEFAULT_CARD_CODE."
            )
        contact.sap_card_code = card_code
        return card_code

    async def create_sales_order(self, order: Order) -> SapOrderResult:
        if not settings.sap_write_enabled:
            raise SapError(
                "La escritura en SAP está deshabilitada "
                "(SAP_WRITE_ENABLED=false)."
            )
        contact = await self.session.get(Contact, order.contact_id)
        if contact is None:
            raise SapError("No se encontró el contacto del pedido.")
        card_code = await self._ensure_bp(contact)

        lines = []
        for item in order.items:
            line = {
                "sku": item.sku,
                "quantity": item.quantity,
                "price": float(item.unit_price),
                "warehouse": item.store_code or settings.sap_warehouse,
            }
            if settings.sap_costing_code:
                line["costingCode"] = settings.sap_costing_code
                if settings.sap_costing_code2:
                    line["costingCode2"] = settings.sap_costing_code2
                if settings.sap_costing_code3:
                    line["costingCode3"] = settings.sap_costing_code3
            if settings.sap_tax_code:
                line["taxCode"] = settings.sap_tax_code
            lines.append(line)

        today = date.today().isoformat()
        try:
            data = await self.post(
                "api/crm/orders",
                {
                    "crmOrderId": order.number,
                    "customerId": card_code,
                    "orderDate": today,
                    "dueDate": today,
                    "warehouse": settings.sap_warehouse,
                    "lines": lines,
                },
            )
        except SapError as exc:
            if "Centro de Costo" in str(exc) or "Costing" in str(exc):
                raise SapError(
                    f"{exc} — el integrador parece desactualizado: hay que "
                    "republicar Integration.Api para que envíe CostingCode/TaxCode."
                ) from exc
            raise
        doc_entry = data.get("sapDocEntry") or data.get("SapDocEntry") or 0
        doc_num = data.get("sapDocNum") or data.get("SapDocNum") or 0
        logger.info(
            "Pedido %s creado vía PaaS (DocEntry=%s)", order.number, doc_entry
        )
        return SapOrderResult(
            doc_entry=int(doc_entry),
            doc_num=int(doc_num),
            total=Decimal(str(order.total)),
        )

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult:
        raise SapError(
            "El integrador todavía no expone facturación: el pedido queda "
            "pagado y pendiente de facturar en SAP."
        )

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult:
        raise SapError(
            "El integrador todavía no expone el registro de pagos en SAP."
        )


class VtexPaas(PaasSap):
    """Read-only PaasVTEX adapter for the informational bot.

    SAP remains available through PaasSap/ServiceLayerSap; each deployment
    selects its provider with SAP_MODE=sap|vtex.
    """

    _cache_ttl = 15.0

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._base_path = "api/vtex"

    async def scroll_customers(
        self, token: str | None = None, size: int = 100
    ) -> dict:
        params: dict = {"size": size}
        if token:
            params["token"] = token
        data = await self.get(
            f"{self._base_path}/customers/scroll",
            params=params,
        )
        return data if isinstance(data, dict) else {}

    async def get_brands(self) -> list[dict]:
        data = await self.get(f"{self._base_path}/brands")
        return data if isinstance(data, list) else []

    async def export_items(
        self,
        after: str | None = None,
        limit: int = 200,
        brand_id: str | None = None,
        price_range: str | None = None,
    ) -> list[dict]:
        params: dict = {"limit": max(1, min(int(limit), 500))}
        if after:
            params["after"] = after
        if brand_id:
            params["brand"] = str(brand_id)
        if price_range:
            params["price"] = price_range
        data = await self.get(
            f"{self._base_path}/items/export",
            params=params,
        )
        return data if isinstance(data, list) else []

    async def get_customer(self, term: str) -> dict | None:
        try:
            data = await self.get(
                f"{self._base_path}/customers/{quote(term, safe='')}"
            )
        except SapNotFound:
            return None
        return data if isinstance(data, dict) else None

    async def get_customer_purchases(
        self, term: str, top: int = 100, skip: int = 0
    ) -> list[dict]:
        data = await self.get(
            f"{self._base_path}/customers/{quote(term, safe='')}/purchases",
            params={"top": top, "skip": skip},
        )
        if not isinstance(data, dict):
            return []
        value = data.get("value")
        return value if isinstance(value, list) else []

    async def get_order(self, order_id: str) -> dict:
        data = await self.get(
            f"{self._base_path}/orders/{quote(order_id, safe='')}"
        )
        return data if isinstance(data, dict) else {}

    async def get_order_by_sequence(self, sequence: str) -> dict | None:
        """Pedido por número de secuencia (ruta explícita, no identidad)."""
        try:
            data = await self.get(
                f"{self._base_path}/orders/by-sequence/{quote(sequence, safe='')}"
            )
        except SapNotFound:
            return None
        return data if isinstance(data, dict) else None

    async def get_orders_page(
        self,
        page: int = 1,
        per_page: int = 100,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> dict:
        params: dict = {"page": page, "perPage": per_page}
        if created_from:
            params["dateFrom"] = created_from
        if created_to:
            params["dateTo"] = created_to
        data = await self.get(
            f"{self._base_path}/orders",
            params=params,
        )
        return data if isinstance(data, dict) else {}

    async def create_sales_order(self, order: Order) -> SapOrderResult:
        raise SapError(
            "El bot está en modo informativo VTEX: no se crean pedidos."
        )

    async def create_invoice_from_order(self, order: Order) -> SapInvoiceResult:
        raise SapError(
            "El bot está en modo informativo VTEX: no se factura."
        )

    async def create_incoming_payment(
        self, order: Order, invoice: SapInvoiceResult
    ) -> SapPaymentResult:
        raise SapError(
            "El bot está en modo informativo VTEX: no se registran pagos."
        )


def get_sap(session: AsyncSession) -> SapAdapter:
    if settings.sap_mode == "vtex":
        return VtexPaas(session)
    if settings.sap_mode == "paas":
        return PaasSap(session)
    if settings.sap_mode != "service_layer":
        return MockSap(session)
    if settings.sap_write_enabled:
        return ServiceLayerSap(session)
    if settings.sap_live_reads:
        return HybridSap(
            reader=_live_reader(),
            writer=MockSap(session),
            ttl_seconds=settings.sap_cache_ttl_seconds,
        )
    return MockSap(session)
