-- Core tables for the Retail and Supply Chain Control Tower

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id          SERIAL PRIMARY KEY,
    supplier_name        TEXT NOT NULL UNIQUE,
    country              TEXT,
    reliability_score    NUMERIC(4,3) NOT NULL CHECK (reliability_score BETWEEN 0 AND 1),
    base_lead_time_days  INTEGER NOT NULL CHECK (base_lead_time_days > 0),
    lead_time_stddev     NUMERIC(5,2) NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS products (
    product_id       INTEGER PRIMARY KEY,
    product_name     TEXT NOT NULL,
    category_id      INTEGER,
    category_name    TEXT,
    department_name  TEXT,
    unit_price       NUMERIC(10,2),
    supplier_id      INTEGER REFERENCES suppliers (supplier_id)
);

CREATE TABLE IF NOT EXISTS orders (
    order_item_id  BIGINT PRIMARY KEY,
    order_id       BIGINT NOT NULL,
    order_ts       TIMESTAMP NOT NULL,
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    market         TEXT,
    order_region   TEXT,
    order_country  TEXT,
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    unit_price     NUMERIC(10,2),
    discount       NUMERIC(10,2),
    sales          NUMERIC(12,2),
    order_status   TEXT,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shipments (
    order_item_id       BIGINT PRIMARY KEY REFERENCES orders (order_item_id),
    shipped_ts          TIMESTAMP,
    shipping_mode       TEXT,
    days_scheduled      INTEGER,
    days_real           INTEGER,
    delivery_status     TEXT,
    late_delivery_risk  SMALLINT,
    is_late             BOOLEAN GENERATED ALWAYS AS (days_real > days_scheduled) STORED
);

CREATE TABLE IF NOT EXISTS supplier_deliveries (
    delivery_id   BIGSERIAL PRIMARY KEY,
    supplier_id   INTEGER NOT NULL REFERENCES suppliers (supplier_id),
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    ordered_ts    TIMESTAMP NOT NULL,
    expected_ts   TIMESTAMP NOT NULL,
    received_ts   TIMESTAMP,
    quantity      INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_ts    TIMESTAMP NOT NULL,
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    market         TEXT NOT NULL,
    on_hand        INTEGER NOT NULL,
    on_order       INTEGER NOT NULL DEFAULT 0,
    reorder_point  INTEGER NOT NULL,
    PRIMARY KEY (snapshot_ts, product_id, market)
);

-- Hidden answer key used only to score the anomaly detector
CREATE TABLE IF NOT EXISTS anomaly_labels (
    label_id      SERIAL PRIMARY KEY,
    anomaly_type  TEXT NOT NULL CHECK (anomaly_type IN ('supplier_delay', 'demand_spike')),
    entity_type   TEXT NOT NULL,
    entity_id     INTEGER NOT NULL,
    start_ts      TIMESTAMP NOT NULL,
    end_ts        TIMESTAMP NOT NULL,
    magnitude     NUMERIC(8,2)
);

-- Indexes for the queries the KPIs and dashboards will run most
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders (order_ts);
CREATE INDEX IF NOT EXISTS idx_orders_product_ts ON orders (product_id, order_ts);
CREATE INDEX IF NOT EXISTS idx_supplier_deliveries_supplier_ts ON supplier_deliveries (supplier_id, ordered_ts);
CREATE INDEX IF NOT EXISTS idx_inventory_product_ts ON inventory_snapshots (product_id, snapshot_ts);
