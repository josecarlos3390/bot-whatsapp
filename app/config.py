from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "chatbot-whatsapp-sapb1"
    app_env: str = "dev"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    admin_token: str = ""
    seed_demo: bool = True
    knowledge_dir: str = "knowledge"
    bot_name: str = "Rohi"
    weather_enabled: bool = False
    weather_city: str = "Santa Cruz"
    weather_latitude: float = -17.7833
    weather_longitude: float = -63.1821

    database_url: str = "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot"
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    queue_enabled: bool = False
    auto_create_db: bool = False
    sap_event_queue_enabled: bool = False
    sap_event_exchange: str = "sap.events"
    sap_event_queue: str = "chatbot.sap.events"
    sap_event_dlq: str = "chatbot.sap.events.dlq"
    sap_event_dlx: str = "chatbot.sap.events.dlx"
    sap_event_prefetch: int = 10
    sap_event_tenant: str = "RETAIL_QA5"

    # WhatsApp Cloud API
    wa_business_number: str = ""
    wa_phone_number_id: str = ""
    wa_waba_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = "dev-verify-token"
    wa_graph_version: str = "v23.0"
    wa_dry_run: bool = True
    wa_native_catalog_enabled: bool = False
    wa_native_cart_enabled: bool = False
    wa_catalog_id: str = ""
    wa_commerce_account_id: str = ""
    meta_catalog_link_base: str = ""
    meta_catalog_placeholder_image: str = ""
    product_image_placeholder: str = ""
    feedback_after_checkout: bool = False
    feedback_delay_days: int = 2
    feedback_outbound_enabled: bool = False
    feedback_template_name: str = "encuesta_atencion"
    feedback_template_lang: str = "es"
    handoff_webhook_url: str = ""
    handoff_notify_enabled: bool = True
    handoff_auto_resume_minutes: int = 5
    handoff_sla_minutes: int = 5
    handoff_reassign_minutes: int = 5
    advisor_session_secret: str = "change-me-advisor-session"
    advisor_session_hours: int = 12
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    # SAP Business One
    sap_mode: str = "mock"  # mock | service_layer | paas
    sap_sl_url: str = ""
    sap_paas_url: str = ""
    sap_paas_api_key: str = ""
    sap_paas_tenant: str = "RETAIL_QA5"
    sap_company_db: str = ""
    sap_user: str = ""
    sap_password: str = ""
    sap_verify_tls: bool = True
    sap_warehouse: str = "01"
    sap_price_list: int = 1
    sap_cash_account: str = ""
    sap_live_reads: bool = False
    sap_write_enabled: bool = False
    # Socio genérico ("Consumidor Final") para clientes sin CardCode. Si está
    # vacío, el checkout exige identificar al cliente o que tenga RUT.
    sap_default_card_code: str = ""
    sap_cache_ttl_seconds: int = 60
    sap_costing_code: str = ""
    sap_costing_code2: str = ""
    sap_costing_code3: str = ""
    sap_tax_code: str = ""
    sap_stores: str = "101-1001=Tienda 1,102-1001=Tienda 2,103-1001=Tienda 3"
    sap_price_cache_ttl_seconds: int = 300
    # Búsqueda en caliente: si el término no está en el catálogo local, se
    # consulta SAP y se guarda la respuesta para la próxima consulta.
    sap_hot_search_enabled: bool = True
    sap_hot_search_limit: int = 8

    @property
    def sap_store_map(self) -> dict[str, str]:
        stores: dict[str, str] = {}
        for raw in self.sap_stores.split(","):
            part = raw.strip()
            if not part:
                continue
            if "=" in part:
                code, name = part.split("=", 1)
            elif ":" in part:
                code, name = part.split(":", 1)
            else:
                code, name = part, part
            stores[code.strip()] = name.strip()
        return stores

    # Pagos
    payment_provider: str = "mock_qr"  # mock_qr | cucu_qr
    payment_ttl_minutes: int = 30
    cucu_api_key: str = ""
    cucu_base_url: str = "https://qrsimple.cucu.bo/api/v1"
    cucu_expiration: str = "30m"
    cucu_webhook_secret: str = ""

    # Memoria
    memory_auto_summary: bool = True


settings = Settings()
