-- Findings from the detectors (the detectors never read anomaly_labels)
CREATE TABLE IF NOT EXISTS detected_anomalies (
    detection_id   BIGSERIAL PRIMARY KEY,
    detector       TEXT NOT NULL CHECK (detector IN ('zscore', 'isolation_forest')),
    anomaly_type   TEXT NOT NULL CHECK (anomaly_type IN ('supplier_delay', 'demand_spike')),
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER NOT NULL,
    event_ts       TIMESTAMP NOT NULL,
    score          NUMERIC(10,3),
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_detected_lookup
    ON detected_anomalies (anomaly_type, entity_id, event_ts);
    