-- KPI 3: supplier lead time per supplier per month
CREATE OR REPLACE VIEW v_kpi_supplier_leadtime AS
SELECT
    s.supplier_id,
    s.supplier_name,
    date_trunc('month', d.ordered_ts)::date               AS month,
    count(*)                                              AS deliveries,
    round(avg(EXTRACT(epoch FROM (d.received_ts - d.ordered_ts)) / 86400)::numeric, 1)  AS avg_lead_time_days,
    round(avg(EXTRACT(epoch FROM (d.received_ts - d.expected_ts)) / 86400)::numeric, 1) AS avg_days_late
FROM supplier_deliveries d
JOIN suppliers s ON s.supplier_id = d.supplier_id
WHERE d.received_ts IS NOT NULL
  AND d.received_ts < (SELECT watermark_ts FROM replay_state WHERE id = 1)
GROUP BY s.supplier_id, s.supplier_name, date_trunc('month', d.ordered_ts);

-- KPI 4: days of inventory per product (latest snapshot before the clock)
CREATE OR REPLACE VIEW v_kpi_days_of_inventory AS
WITH clock AS (
    SELECT watermark_ts FROM replay_state WHERE id = 1
),
latest AS (
    SELECT DISTINCT ON (i.product_id)
           i.product_id, i.snapshot_ts, i.on_hand, i.on_order, i.reorder_point
    FROM inventory_snapshots i, clock c
    WHERE i.snapshot_ts < c.watermark_ts
    ORDER BY i.product_id, i.snapshot_ts DESC
),
demand AS (
    SELECT o.product_id, sum(o.quantity) / 14.0 AS daily_demand
    FROM orders o, clock c
    WHERE o.order_ts >= c.watermark_ts - interval '14 days'
      AND o.order_ts <  c.watermark_ts
    GROUP BY o.product_id
)
SELECT
    l.product_id,
    p.product_name,
    sp.supplier_name,
    l.snapshot_ts::date                                   AS as_of_day,
    l.on_hand,
    l.on_order,
    l.reorder_point,
    round(COALESCE(d.daily_demand, 0)::numeric, 2)        AS daily_demand_14d,
    CASE WHEN COALESCE(d.daily_demand, 0) > 0
         THEN round((l.on_hand / d.daily_demand)::numeric, 1)
    END                                                   AS days_of_inventory
FROM latest l
JOIN products p ON p.product_id = l.product_id
LEFT JOIN suppliers sp ON sp.supplier_id = p.supplier_id
LEFT JOIN demand d ON d.product_id = l.product_id;