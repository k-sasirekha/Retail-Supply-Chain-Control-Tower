"""Detect demand spikes and supplier delays with a z-score baseline and an Isolation Forest.

These detectors never read anomaly_labels. Results go to detected_anomalies.
Re-running replaces the previous results.
"""
import logging
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SEED = 42
END_DAY = pd.Timestamp("2018-01-31")
WINDOW_DAYS = 28
MIN_HISTORY_DAYS = 14
DEMAND_Z = 4.0
DEMAND_MIN_UNITS = 10
DEMAND_IF_CONTAMINATION = 0.002
DELAY_Z = 3.5
DELAY_IF_CONTAMINATION = 0.03


def load_daily_demand(engine: Engine) -> pd.DataFrame:
    """Units sold per product per day."""
    sql = text(
        "SELECT product_id, CAST(order_ts AS date) AS day, sum(quantity) AS qty "
        "FROM orders GROUP BY product_id, CAST(order_ts AS date)"
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def demand_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Add each product-day's previous-28-day mean and std, a z-score and a ratio."""
    frames = []
    for pid, grp in daily.groupby("product_id"):
        s = grp.set_index(pd.to_datetime(grp["day"]))["qty"].astype(float)
        s = s.reindex(pd.date_range(s.index.min(), END_DAY), fill_value=0.0)
        prev = s.shift(1)
        roll = prev.rolling(WINDOW_DAYS, min_periods=MIN_HISTORY_DAYS)
        frames.append(
            pd.DataFrame(
                {
                    "product_id": int(pid),
                    "day": s.index,
                    "qty": s.to_numpy(),
                    "mean": roll.mean().to_numpy(),
                    "std": roll.std().to_numpy(),
                }
            )
        )
    feats = pd.concat(frames, ignore_index=True).dropna(subset=["mean", "std"])
    feats["z"] = (feats["qty"] - feats["mean"]) / feats["std"].clip(lower=1.0)
    feats["ratio"] = feats["qty"] / (feats["mean"] + 1.0)
    return feats


def demand_zscore(feats: pd.DataFrame) -> pd.DataFrame:
    """Baseline: flag days far above the product's own recent normal."""
    hits = feats[(feats["z"] >= DEMAND_Z) & (feats["qty"] >= DEMAND_MIN_UNITS)]
    return to_findings(hits["product_id"], hits["day"], hits["z"], "zscore", "demand_spike", "product")


def demand_isolation_forest(feats: pd.DataFrame) -> pd.DataFrame:
    """Isolation Forest on days where demand is above normal."""
    rows = feats[feats["qty"] > feats["mean"]].copy()
    x = np.column_stack([np.log1p(rows["qty"]), np.log1p(rows["ratio"]), rows["z"].clip(-10, 50)])
    model = IsolationForest(contamination=DEMAND_IF_CONTAMINATION, random_state=SEED).fit(x)
    flagged = model.predict(x) == -1
    scores = -model.score_samples(x)
    return to_findings(
        rows["product_id"][flagged], rows["day"][flagged], pd.Series(scores, index=rows.index)[flagged],
        "isolation_forest", "demand_spike", "product",
    )


def load_deliveries(engine: Engine) -> pd.DataFrame:
    """Every delivery that has arrived, with how late it was versus expected."""
    sql = text(
        "SELECT supplier_id, ordered_ts, "
        "EXTRACT(epoch FROM (received_ts - expected_ts))::float8 / 86400 AS late_days "
        "FROM supplier_deliveries WHERE received_ts IS NOT NULL"
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    grp = df.groupby("supplier_id")["late_days"]
    median = grp.transform("median")
    mad = grp.transform(lambda x: (x - x.median()).abs().median()) * 1.4826
    df["z"] = (df["late_days"] - median) / mad.clip(lower=1.0)
    return df


def delay_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Baseline: flag deliveries far later than that supplier's normal."""
    hits = df[df["z"] >= DELAY_Z]
    return to_findings(hits["supplier_id"], hits["ordered_ts"], hits["z"], "zscore", "supplier_delay", "supplier")


def delay_isolation_forest(df: pd.DataFrame) -> pd.DataFrame:
    """Isolation Forest on (lateness, robust z-score); only late deliveries are kept."""
    x = np.column_stack([df["late_days"], df["z"].clip(-10, 50)])
    model = IsolationForest(contamination=DELAY_IF_CONTAMINATION, random_state=SEED).fit(x)
    flagged = (model.predict(x) == -1) & (df["z"].to_numpy() > 0)
    scores = pd.Series(-model.score_samples(x), index=df.index)
    return to_findings(
        df["supplier_id"][flagged], df["ordered_ts"][flagged], scores[flagged],
        "isolation_forest", "supplier_delay", "supplier",
    )


def to_findings(
    entity_id: pd.Series, event_ts: pd.Series, score: pd.Series, detector: str, anomaly_type: str, entity_type: str
) -> pd.DataFrame:
    """Shape results to match the detected_anomalies table."""
    return pd.DataFrame(
        {
            "detector": detector,
            "anomaly_type": anomaly_type,
            "entity_type": entity_type,
            "entity_id": entity_id.astype(int).to_numpy(),
            "event_ts": pd.to_datetime(event_ts).to_numpy(),
            "score": score.astype(float).round(3).to_numpy(),
        }
    )


def main() -> None:
    """Run all four detectors and store their findings."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())

    feats = demand_features(load_daily_demand(engine))
    deliveries = load_deliveries(engine)
    results = pd.concat(
        [
            demand_zscore(feats),
            demand_isolation_forest(feats),
            delay_zscore(deliveries),
            delay_isolation_forest(deliveries),
        ],
        ignore_index=True,
    )

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE detected_anomalies RESTART IDENTITY"))
    results.to_sql("detected_anomalies", engine, if_exists="append", index=False, chunksize=5000, method="multi")

    for (detector, kind), n in results.groupby(["detector", "anomaly_type"]).size().items():
        log.info("%s / %s: %d detections", detector, kind, n)
    log.info("Done in %.1fs.", time.perf_counter() - started)


if __name__ == "__main__":
    main()