from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    phone_e164: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    sap_card_code: Mapped[str | None] = mapped_column(String(20))
    opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="open")
    bot_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    last_query: Mapped[str | None] = mapped_column(String(300))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped[Contact] = relationship(lazy="selectin")


class ConversationState(Base):
    """Slots estructurados para no perder rubro/marca/medida entre turnos."""

    __tablename__ = "conversation_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    category: Mapped[str | None] = mapped_column(String(80))
    brand: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(40))
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    intent: Mapped[str | None] = mapped_column(String(40))
    last_sku: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AreaRule(Base):
    """Reglas de negocio por área, editables desde el panel."""

    __tablename__ = "area_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    area: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160))
    rule_type: Mapped[str] = mapped_column(String(40), index=True)
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(120), default="admin")
    updated_by: Mapped[str] = mapped_column(String(120), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AreaRuleVersion(Base):
    """Snapshot de cada cambio para auditoría y rollback."""

    __tablename__ = "area_rule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("area_rules.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    changed_by: Mapped[str] = mapped_column(String(120), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AreaUser(Base):
    """Usuario encargado de cargar reglas de un área."""

    __tablename__ = "area_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    area: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationFlow(Base):
    """Flujo conversacional activo, por ejemplo una devolución."""

    __tablename__ = "conversation_flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    flow: Mapped[str] = mapped_column(String(40), default="return")
    step: Mapped[int] = mapped_column(Integer, default=0)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationRecommendation(Base):
    """Última recomendación mostrada, para poder justificarla después."""

    __tablename__ = "conversation_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    query: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(80))
    brand: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(40))
    min_price: Mapped[float | None] = mapped_column(Float)
    max_price: Mapped[float | None] = mapped_column(Float)
    products: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationGuard(Base):
    """Pregunta pendiente y control de repeticiones de una conversación."""

    __tablename__ = "conversation_guards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    pending_slot: Mapped[str | None] = mapped_column(String(40))
    pending_question: Mapped[str | None] = mapped_column(String(500))
    pending_query: Mapped[str | None] = mapped_column(String(200))
    last_answer: Mapped[str | None] = mapped_column(String(1000))
    repeat_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SemanticCache(Base):
    """Expansión semántica de consultas, cacheada para no repetir el LLM."""

    __tablename__ = "semantic_cache"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    query: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Occasion(Base):
    """Campaña u ocasión administrable: Halloween, Navidad, mudanza, etc."""

    __tablename__ = "occasions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    direct: Mapped[list] = mapped_column(JSON, default=list)
    exclude: Mapped[list] = mapped_column(JSON, default=list)
    exclude_categories: Mapped[list] = mapped_column(JSON, default=list)
    bridges: Mapped[list] = mapped_column(JSON, default=list)
    area: Mapped[str] = mapped_column(String(40), default="marketing", index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(120), default="admin")
    updated_by: Mapped[str] = mapped_column(String(120), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), unique=True, index=True
    )
    city: Mapped[str | None] = mapped_column(String(80))
    preferred_store: Mapped[str | None] = mapped_column(String(20))
    birthday: Mapped[date | None] = mapped_column(Date)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CustomerCandidate(Base):
    __tablename__ = "customer_candidates"
    __table_args__ = (
        UniqueConstraint("contact_id", "card_code", name="uq_customer_candidate"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    card_code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(200))
    name_masked: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerFact(Base):
    __tablename__ = "customer_facts"
    __table_args__ = (
        UniqueConstraint("contact_id", "key", name="uq_customer_fact_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="whatsapp")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    summary: Mapped[str] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    type: Mapped[str] = mapped_column(String(24), default="text")
    text: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "sku", name="uq_cart_sku"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cart_id: Mapped[str] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    list_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), default=Decimal("0")
    )
    store_code: Mapped[str | None] = mapped_column(String(20))

    cart: Mapped[Cart] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    cart_id: Mapped[str] = mapped_column(ForeignKey("carts.id"))
    status: Mapped[str] = mapped_column(String(24), default="pending_payment")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    sap_doc_entry: Mapped[int | None] = mapped_column(Integer)
    sap_doc_num: Mapped[int | None] = mapped_column(Integer)
    invoice_doc_entry: Mapped[int | None] = mapped_column(Integer)
    invoice_doc_num: Mapped[int | None] = mapped_column(Integer)
    sap_payment_doc_entry: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    list_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), default=Decimal("0")
    )
    store_code: Mapped[str | None] = mapped_column(String(20))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    order: Mapped[Order] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="mock_qr")
    provider_ref: Mapped[str | None] = mapped_column(String(128), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    qr_payload: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_doc_entry: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(128), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseHistory(Base):
    __tablename__ = "purchase_history"
    __table_args__ = (
        UniqueConstraint(
            "contact_id", "doc_type", "sap_doc_entry",
            name="uq_purchase_doc",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    sap_doc_entry: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[str] = mapped_column(String(20), default="invoice")
    doc_num: Mapped[int | None] = mapped_column(Integer)
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class PurchaseHistoryLine(Base):
    __tablename__ = "purchase_history_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    history_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_history.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(80))
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    foreign_name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    group_code: Mapped[int | None] = mapped_column(Integer)
    group_name: Mapped[str | None] = mapped_column(String(80))
    brand: Mapped[str | None] = mapped_column(String(80))
    manufacturer_code: Mapped[int | None] = mapped_column(Integer)
    # Código de barra vigente (SAP BarCode). Se guarda sólo con dígitos.
    barcode: Mapped[str | None] = mapped_column(String(32), index=True)
    # Ficha ampliada de SAP: familia, línea, grupo, peso, modelo, descripción.
    attributes: Mapped[dict | None] = mapped_column(JSON)
    sales_unit: Mapped[str | None] = mapped_column(String(20))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="BOB")
    stock: Mapped[int] = mapped_column(default=0)
    image_url: Mapped[str | None] = mapped_column(String(500))
    keywords: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sap_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    sap_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("sku", "url", name="uq_product_image_sku_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    alt: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str | None] = mapped_column(String(80))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ProductPromotion(Base):
    __tablename__ = "product_promotions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), default=Decimal("0")
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    tier_quantity: Mapped[int | None] = mapped_column(Integer)
    price_list: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(32), default="sap_special_price")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class FeedbackRequest(Base):
    __tablename__ = "feedback_requests"
    __table_args__ = (
        UniqueConstraint("order_id", "type", name="uq_feedback_request_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20), default="delivery")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CustomerFeedback(Base):
    __tablename__ = "customer_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(20), default="open")
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(64), index=True)
    consent: Mapped[bool] = mapped_column(Boolean, default=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class HandoffNote(Base):
    __tablename__ = "handoff_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    handoff_id: Mapped[str] = mapped_column(
        ForeignKey("handoffs.id", ondelete="CASCADE"), index=True
    )
    advisor: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class HandoffRead(Base):
    __tablename__ = "handoff_reads"
    __table_args__ = (
        UniqueConstraint("handoff_id", "advisor", name="uq_handoff_read"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    handoff_id: Mapped[str] = mapped_column(
        ForeignKey("handoffs.id", ondelete="CASCADE"), index=True
    )
    advisor: Mapped[str] = mapped_column(String(120), index=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Advisor(Base):
    __tablename__ = "advisors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default="agent")
    on_duty: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class HandoffEvent(Base):
    __tablename__ = "handoff_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    handoff_id: Mapped[str] = mapped_column(
        ForeignKey("handoffs.id", ondelete="CASCADE"), index=True
    )
    advisor: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class HandoffSurvey(Base):
    __tablename__ = "handoff_surveys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    handoff_id: Mapped[str] = mapped_column(
        ForeignKey("handoffs.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="received")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class ProductSalesStat(Base):
    __tablename__ = "product_sales_stats"

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    units_30d: Mapped[int] = mapped_column(Integer, default=0)
    revenue_30d: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    units_90d: Mapped[int] = mapped_column(Integer, default=0)
    revenue_90d: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    last_sale_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SapEventInbox(Base):
    __tablename__ = "sap_event_inbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="")
    event_type: Mapped[str] = mapped_column(String(32), default="")
    object_type: Mapped[str] = mapped_column(String(30), default="")
    aggregate_id: Mapped[str] = mapped_column(String(128), default="")
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)



class QueryLearning(Base):
    """Búsquedas que no encontraban nada y cómo se resolvieron.

    Guarda el término del cliente, la consulta que sí funcionó (aprendida con
    el modelo) y cuántas veces falló. Así el bot mejora solo: la próxima vez
    resuelve el mismo término sin consultar la IA.
    """

    __tablename__ = "query_learning"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    term: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    query: Mapped[str | None] = mapped_column(String(300))
    producto: Mapped[str | None] = mapped_column(String(120))
    atributos: Mapped[str | None] = mapped_column(String(300))
    hits: Mapped[int] = mapped_column(Integer, default=0)
    misses: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="ia")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    assigned_to: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    resolution_category: Mapped[str | None] = mapped_column(String(40))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FunnelEvent(Base):
    """Paso del embudo de venta (búsqueda, ficha, carrito, checkout, pago).

    Independiente de si el carrito es propio o el nativo de WhatsApp: lo que
    importa es el paso, el contacto y el artículo.
    """

    __tablename__ = "funnel_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    step: Mapped[str] = mapped_column(String(32), index=True)
    contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    sku: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(String(160))
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
