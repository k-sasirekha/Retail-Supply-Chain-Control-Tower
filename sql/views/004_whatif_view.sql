-- What-if: how does a supplier delay (in days) move each product's stock-out day?
-- Delay 0 reproduces stock_risk.stockout_day_expected. Day 1 = the replay-clock day.
CREATE OR REPLACE VIEW v_whatif_stockout AS
WITH delays(delay_days) AS (
    VALUES (0), (3), (5), (7), (10), (14)
),
risk AS (
    SELECT product_id, as_of_ts, on_hand FROM stock_risk
),
arr AS (
    -- deliveries ordered before the clock and still on the way, by arrival day
    SELECT d.product_id,
           (d.received_ts::date - r.as_of_ts::date) + 1 AS day_no,
           sum(d.quantity)                              AS qty
    FROM supplier_deliveries d
    JOIN risk r ON r.product_id = d.product_id
    WHERE d.ordered_ts < r.as_of_ts
      AND d.received_ts >= r.as_of_ts
    GROUP BY d.product_id, (d.received_ts::date - r.as_of_ts::date) + 1
),
grid AS (
    SELECT r.product_id, r.on_hand, dl.delay_days, f.day_no, f.expected
    FROM risk r
    CROSS JOIN delays dl
    JOIN stock_forecast_daily f ON f.product_id = r.product_id
),
proj AS (
    -- projected stock = on hand + arrivals (shifted later by the delay) - expected demand so far
    SELECT g.product_id, g.delay_days, g.day_no,
           g.on_hand
           + COALESCE((SELECT sum(a.qty) FROM arr a
                       WHERE a.product_id = g.product_id
                         AND a.day_no + g.delay_days <= g.day_no), 0)
           - sum(g.expected) OVER (PARTITION BY g.product_id, g.delay_days
                                   ORDER BY g.day_no) AS stock
    FROM grid g
),
res AS (
    SELECT product_id, delay_days,
           min(day_no) FILTER (WHERE stock <= 0) AS stockout_day
    FROM proj
    GROUP BY product_id, delay_days
)
SELECT r.product_id,
       p.product_name,
       s.supplier_name,
       r.delay_days,
       r.stockout_day,
       b.stockout_day AS baseline_stockout_day,
       COALESCE(b.stockout_day, 15) - COALESCE(r.stockout_day, 15) AS days_earlier,
       CASE WHEN r.stockout_day <= 7 THEN 'high'
            WHEN r.stockout_day IS NOT NULL THEN 'medium'
            ELSE 'low' END AS whatif_risk
FROM res r
JOIN res b ON b.product_id = r.product_id AND b.delay_days = 0
JOIN products p ON p.product_id = r.product_id
LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id;