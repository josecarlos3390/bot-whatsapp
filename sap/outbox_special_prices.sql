-- =============================================================================
-- SBO_SP_PostTransactionNotice: eventos para integration-paas / chatbot
--
-- 1. En el bloque DECLARE inicial del procedure, agregar:
--
--    DECLARE v_payload       NCLOB;
--    DECLARE v_key_columns   NVARCHAR(255);
--    DECLARE v_key_values    NVARCHAR(500);
--
-- 2. Cambiar el tenant existente:
--
--    v_tenant_id NVARCHAR(64) := 'tenant-001';
--
-- 3. Pegar los bloques de abajo después del bloque de proveedores y antes
--    de la llamada a BAG_COLA_SYNC_A_ZOHO_Y_WOO.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Clientes (Business Partner, CardType = C)
-- -----------------------------------------------------------------------------
IF object_type = '2'
   AND transaction_type IN ('A', 'U', 'D')
THEN
    v_aggregate_id := :list_of_cols_val_tab_del;

    SELECT "CardType"
      INTO v_card_type
      FROM "OCRD"
     WHERE "CardCode" = :v_aggregate_id;

    IF :v_card_type = 'C' THEN

        v_event_type :=
            CASE :transaction_type
                WHEN 'A' THEN 'Created'
                WHEN 'U' THEN 'Updated'
                WHEN 'D' THEN 'Deleted'
            END;

        INSERT INTO INTEGRATION_BUS.OUTBOX_EVENTS
        (
            ID, TENANT_ID, EVENT_TYPE, OBJECT_TYPE, AGGREGATE_ID, PAYLOAD,
            OCCURRED_AT, PROCESSED_AT, ATTEMPT_COUNT, ERROR_MESSAGE,
            IS_DEAD_LETTER
        )
        VALUES
        (
            SYSUUID,
            :v_tenant_id,
            :v_event_type,
            '2',
            :v_aggregate_id,
            NULL,
            CURRENT_TIMESTAMP, NULL, 0, NULL, 0
        );

    END IF;
END IF;

-- -----------------------------------------------------------------------------
-- Artículos (ItemCode)
-- -----------------------------------------------------------------------------
IF object_type = '4'
   AND transaction_type IN ('A', 'U', 'D')
THEN
    v_event_type :=
        CASE :transaction_type
            WHEN 'A' THEN 'Created'
            WHEN 'U' THEN 'Updated'
            WHEN 'D' THEN 'Deleted'
        END;

    INSERT INTO INTEGRATION_BUS.OUTBOX_EVENTS
    (
        ID, TENANT_ID, EVENT_TYPE, OBJECT_TYPE, AGGREGATE_ID, PAYLOAD,
        OCCURRED_AT, PROCESSED_AT, ATTEMPT_COUNT, ERROR_MESSAGE,
        IS_DEAD_LETTER
    )
    VALUES
    (
        SYSUUID,
        'tenant-001',
        :v_event_type,
        '4',
        :list_of_cols_val_tab_del,
        NULL,
        CURRENT_TIMESTAMP, NULL, 0, NULL, 0
    );
END IF;

-- -----------------------------------------------------------------------------
-- Special Prices (CardCode + ItemCode)
--
-- El evento guarda las claves en PAYLOAD; el worker del PaaS consulta el
-- detalle real en el Service Layer y publica un evento normalizado.
-- -----------------------------------------------------------------------------
IF object_type = '7'
   AND transaction_type IN ('A', 'U', 'D')
THEN
    v_event_type :=
        CASE :transaction_type
            WHEN 'A' THEN 'Created'
            WHEN 'U' THEN 'Updated'
            WHEN 'D' THEN 'Deleted'
        END;

    v_key_columns := :list_of_key_cols_tab_del;
    v_key_values  := :list_of_cols_val_tab_del;

    v_payload :=
        '{"keyColumns":"' ||
        REPLACE(:v_key_columns, '"', '\"') ||
        '","keyValues":"' ||
        REPLACE(:v_key_values, '"', '\"') ||
        '"}';

    INSERT INTO INTEGRATION_BUS.OUTBOX_EVENTS
    (
        ID, TENANT_ID, EVENT_TYPE, OBJECT_TYPE, AGGREGATE_ID, PAYLOAD,
        OCCURRED_AT, PROCESSED_AT, ATTEMPT_COUNT, ERROR_MESSAGE,
        IS_DEAD_LETTER
    )
    VALUES
    (
        SYSUUID,
        'tenant-001',
        :v_event_type,
        '7',
        :v_key_values,
        :v_payload,
        CURRENT_TIMESTAMP, NULL, 0, NULL, 0
    );
END IF;

-- -----------------------------------------------------------------------------
-- Facturas y pedidos (DocEntry)
-- -----------------------------------------------------------------------------
IF object_type IN ('13', '17')
   AND transaction_type IN ('A', 'U', 'D')
THEN
    v_event_type :=
        CASE :transaction_type
            WHEN 'A' THEN 'Created'
            WHEN 'U' THEN 'Updated'
            WHEN 'D' THEN 'Deleted'
        END;

    INSERT INTO INTEGRATION_BUS.OUTBOX_EVENTS
    (
        ID, TENANT_ID, EVENT_TYPE, OBJECT_TYPE, AGGREGATE_ID, PAYLOAD,
        OCCURRED_AT, PROCESSED_AT, ATTEMPT_COUNT, ERROR_MESSAGE,
        IS_DEAD_LETTER
    )
    VALUES
    (
        SYSUUID,
        'tenant-001',
        :v_event_type,
        :object_type,
        :list_of_cols_val_tab_del,
        NULL,
        CURRENT_TIMESTAMP, NULL, 0, NULL, 0
    );
END IF;
