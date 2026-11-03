-- Prophet's expected demand per day for the 14-day horizon (used by the what-if view)
CREATE TABLE IF NOT EXISTS stock_forecast_daily (
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    day_no         SMALLINT NOT NULL CHECK (day_no BETWEEN 1 AND 14),
    expected       NUMERIC(10,3) NOT NULL,
    expected_high  NUMERIC(10,3) NOT NULL,
    PRIMARY KEY (product_id, day_no)
);