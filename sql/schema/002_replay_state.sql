-- Virtual clock for replaying history one slice per hourly run
CREATE TABLE IF NOT EXISTS replay_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    watermark_ts     TIMESTAMP NOT NULL,
    slice_hours      INTEGER NOT NULL DEFAULT 24 CHECK (slice_hours > 0),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Start the clock at the beginning of the data (only inserted once)
INSERT INTO replay_state (id, watermark_ts, slice_hours)
VALUES (1, '2017-01-01 00:00:00', 24)
ON CONFLICT (id) DO NOTHING;

-- Log of every pipeline run, used later for your run-time numbers
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id         BIGSERIAL PRIMARY KEY,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    from_ts        TIMESTAMP NOT NULL,
    to_ts          TIMESTAMP NOT NULL,
    orders_seen    INTEGER,
    status         TEXT NOT NULL DEFAULT 'running'
);