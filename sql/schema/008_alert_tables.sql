-- Alert rules (thresholds live here, not in code) and the log used for deduplication
CREATE TABLE IF NOT EXISTS alert_config (
    rule_name       TEXT PRIMARY KEY,
    description     TEXT NOT NULL,
    comparison      TEXT NOT NULL CHECK (comparison IN ('gt', 'lt')),
    threshold       NUMERIC(10,2) NOT NULL,
    min_volume      NUMERIC(10,2),
    severity        TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
    cooldown_hours  INTEGER NOT NULL DEFAULT 6 CHECK (cooldown_hours >= 0),
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_log (
    alert_id      BIGSERIAL PRIMARY KEY,
    rule_name     TEXT NOT NULL REFERENCES alert_config (rule_name),
    entity_key    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    message       TEXT NOT NULL,
    metric_value  NUMERIC(12,2) NOT NULL,
    threshold     NUMERIC(10,2) NOT NULL,
    data_ts       TIMESTAMP NOT NULL,
    fired_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    slack_status  TEXT NOT NULL DEFAULT 'pending',
    email_status  TEXT NOT NULL DEFAULT 'pending'
);

-- The deduplication check looks up the latest alert per rule and entity
CREATE INDEX IF NOT EXISTS idx_alert_log_dedup ON alert_log (rule_name, entity_key, fired_at DESC);