-- Current stock-out risk per product: forecast demand vs stock and incoming deliveries
CREATE TABLE IF NOT EXISTS stock_risk (
    product_id             INTEGER PRIMARY KEY REFERENCES products (product_id),
    as_of_ts               TIMESTAMP NOT NULL,
    on_hand                INTEGER NOT NULL,
    on_order               INTEGER NOT NULL,
    incoming_14d           INTEGER NOT NULL,
    forecast_14d           NUMERIC(10,1) NOT NULL,
    forecast_14d_high      NUMERIC(10,1) NOT NULL,
    days_of_cover          NUMERIC(8,1),
    stockout_day_expected  SMALLINT,
    stockout_day_high      SMALLINT,
    risk_level             TEXT NOT NULL CHECK (risk_level IN ('high', 'medium', 'low')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);