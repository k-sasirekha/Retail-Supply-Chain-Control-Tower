-- KPI 1: stock-out rate per day (share of products with zero stock)
CREATE OR REPLACE VIEW v_kpi_stockout_daily AS
SELECT
    s.snapshot_ts::date                                   AS day,
    count(*)                                              AS products_tracked,
    count(*) FILTER (WHERE s.on_hand = 0)                 AS products_out_of_stock,
    round(100.0 * count(*) FILTER (WHERE s.on_hand = 0) / count(*), 2) AS stockout_rate_pct
FROM inventory_snapshots s
WHERE s.snapshot_ts < (SELECT watermark_ts FROM replay_state WHERE id = 1)
GROUP BY s.snapshot_ts::date;

-- KPI 2: on-time delivery rate per day, by shipping mode
CREATE OR REPLACE VIEW v_kpi_ontime_daily AS
SELECT
    o.order_ts::date                                      AS day,
    sh.shipping_mode,
    count(*)                                              AS shipments,
    count(*) FILTER (WHERE NOT sh.is_late)                AS on_time,
    round(100.0 * count(*) FILTER (WHERE NOT sh.is_late) / count(*), 2) AS ontime_rate_pct
FROM shipments sh
JOIN orders o ON o.order_item_id = sh.order_item_id
WHERE o.order_ts < (SELECT watermark_ts FROM replay_state WHERE id = 1)
GROUP BY o.order_ts::date, sh.shipping_mode;