-- Prophet backtest results: forecast vs naive baseline vs what really sold
CREATE TABLE IF NOT EXISTS demand_forecasts (
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    day           DATE NOT NULL,
    yhat          NUMERIC(10,2) NOT NULL,
    yhat_lower    NUMERIC(10,2) NOT NULL,
    yhat_upper    NUMERIC(10,2) NOT NULL,
    naive         NUMERIC(10,2) NOT NULL,
    actual_real   NUMERIC(10,2) NOT NULL,
    actual_total  NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (product_id, day)
);