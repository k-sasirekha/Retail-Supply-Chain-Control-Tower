"""Version 2 demand-spike detector: a robust baseline that skips the most recent days.

Only the 'robust_zscore' rows in detected_anomalies are replaced when this runs.
It never reads anomaly_labels.
"""
import logging
import time

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DETECTOR = "robust_zscore"
END_DAY = pd.Timestamp("2018-01-31")
SKIP_DAYS = 3
WINDOW_DAYS = 28
MIN_HISTORY_DAYS = 10
ROBUST_Z = 6.0
MIN_UNITS = 8


def robust_baseline(s: pd.Series) -> pd.DataFrame:
    """Median and MAD of the 28 days ending SKIP_DAYS+1 days before each day."""
    lagged = s.shift(SKIP_DAYS + 1)
    roll = lagged.rolling(WINDOW_DAYS, min_periods=MIN_HISTORY_DAYS)
    median = roll.median()
    mad = roll.apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True) * 1.4826
    return pd.DataFrame({"qty": s, "median": median, "mad": mad})


def detect(daily: pd.DataFrame) -> pd.DataFrame:
    """Flag days far above the product's robust normal."""
    found = []
    for pid, grp in daily.groupby("product_id"):
        s = grp.set_index(pd.to_datetime(grp["day"]))["qty"].astype(float)
        s = s.reindex(pd.date_range(s.index.min(), END_DAY), fill_value=0.0)
        b = robust_baseline(s).dropna()
        b["z"] = (b["qty"] - b["median"]) / b["mad"].clip(lower=1.0)
        hits = b[(b["z"] >= ROBUST_Z) & (b["qty"] >= MIN_UNITS)]
        for day, z in hits["z"].items():
            found.append((int(pid), day, float(z)))
    return pd.DataFrame(
        {
            "detector": DETECTOR,
            "anomaly_type": "demand_spike",
            "entity_type": "product",
            "entity_id": [f[0] for f in found],
            "event_ts": [f[1] for f in found],
            "score": [round(f[2], 3) for f in found],
        }
    )


def main() -> None:
    """Run the v2 detector and store its findings."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        daily = pd.read_sql(
            text(
                "SELECT product_id, CAST(order_ts AS date) AS day, sum(quantity) AS qty "
                "FROM orders GROUP BY product_id, CAST(order_ts AS date)"
            ),
            conn,
        )
    results = detect(daily)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM detected_anomalies WHERE detector = :d"), {"d": DETECTOR})
    results.to_sql("detected_anomalies", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    log.info(
        "%s / demand_spike: %d detections on %d products. Done in %.1fs.",
        DETECTOR, len(results), results["entity_id"].nunique(), time.perf_counter() - started,
    )


if __name__ == "__main__":
    main()