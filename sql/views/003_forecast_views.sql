-- Stock risk with product and supplier names, for the dashboard
CREATE OR REPLACE VIEW v_stock_risk AS
SELECT
    r.product_id,
    p.product_name,
    s.supplier_name,
    r.as_of_ts::date          AS as_of_day,
    r.on_hand,
    r.incoming_14d,
    r.forecast_14d,
    r.days_of_cover,
    r.stockout_day_expected,
    r.stockout_day_high,
    r.risk_level
FROM stock_risk r
JOIN products p ON p.product_id = r.product_id
LEFT JOIN suppliers s ON s.supplier_id = p.supplier_id;

-- Detector scores against the labeled anomalies (same logic as score_detectors.py)
CREATE OR REPLACE VIEW v_detector_scores AS
WITH rec AS (
    SELECT d.detector, l.anomaly_type, count(*) AS labels,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM detected_anomalies x
               WHERE x.detector = d.detector AND x.anomaly_type = l.anomaly_type
                 AND x.entity_id = l.entity_id
                 AND x.event_ts >= l.start_ts AND x.event_ts < l.end_ts)) AS caught
    FROM anomaly_labels l
    JOIN (SELECT DISTINCT detector, anomaly_type FROM detected_anomalies) d
      ON d.anomaly_type = l.anomaly_type
    GROUP BY d.detector, l.anomaly_type
),
prec AS (
    SELECT x.detector, x.anomaly_type, count(*) AS detections,
           count(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM anomaly_labels l
               WHERE l.anomaly_type = x.anomaly_type AND l.entity_id = x.entity_id
                 AND x.event_ts >= l.start_ts AND x.event_ts < l.end_ts)) AS correct
    FROM detected_anomalies x
    GROUP BY x.detector, x.anomaly_type
)
SELECT r.detector, r.anomaly_type, r.labels, r.caught, p.detections, p.correct,
       round(100.0 * r.caught / r.labels, 1)                   AS recall_pct,
       round(100.0 * p.correct / NULLIF(p.detections, 0), 1)   AS precision_pct
FROM rec r
JOIN prec p USING (detector, anomaly_type);