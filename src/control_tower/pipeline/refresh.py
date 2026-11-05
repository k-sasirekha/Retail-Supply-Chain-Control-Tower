"""One incremental refresh step: move the replay clock forward and log the run."""
import logging
import sys
from datetime import timedelta

from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_END = "2018-01-31 23:59:59"


def refresh_once() -> dict:
    """Advance the watermark by one slice and record what was processed.

    Returns a small dict describing the run (also written to pipeline_runs).
    """
    engine = create_engine(config.database_url())
    with engine.begin() as conn:
        watermark, slice_hours = conn.execute(
            text("SELECT watermark_ts, slice_hours FROM replay_state WHERE id = 1 FOR UPDATE")
        ).one()
        data_end = conn.execute(text("SELECT CAST(:e AS timestamp)"), {"e": DATA_END}).scalar_one()

        if watermark >= data_end:
            log.info("Watermark %s is at the end of the data. Nothing to do.", watermark)
            return {"status": "caught_up", "from_ts": watermark, "to_ts": watermark, "orders_seen": 0}

        new_watermark = min(watermark + timedelta(hours=slice_hours), data_end)
        run_id = conn.execute(
            text(
                "INSERT INTO pipeline_runs (from_ts, to_ts) VALUES (:f, :t) RETURNING run_id"
            ),
            {"f": watermark, "t": new_watermark},
        ).scalar_one()

        orders_seen = conn.execute(
            text("SELECT count(*) FROM orders WHERE order_ts >= :f AND order_ts < :t"),
            {"f": watermark, "t": new_watermark},
        ).scalar_one()

        conn.execute(
            text("UPDATE replay_state SET watermark_ts = :t, updated_at = now() WHERE id = 1"),
            {"t": new_watermark},
        )
        conn.execute(
            text(
                "UPDATE pipeline_runs SET finished_at = clock_timestamp(), orders_seen = :n, status = 'success' "
                "WHERE run_id = :r"
            ),
            {"n": orders_seen, "r": run_id},
        )

    log.info("Run %d: %s -> %s, %d order lines", run_id, watermark, new_watermark, orders_seen)
    return {"status": "success", "from_ts": watermark, "to_ts": new_watermark, "orders_seen": orders_seen}


if __name__ == "__main__":
    result = refresh_once()
    sys.exit(0 if result["status"] in ("success", "caught_up") else 1)