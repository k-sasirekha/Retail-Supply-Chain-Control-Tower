"""Score detector output against the hidden answer key (anomaly_labels).

A detection is correct if it names the same product or supplier as a label,
and its event time falls inside that label's window.
"""
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

RECALL_SQL = """
SELECT d.detector, l.anomaly_type, count(*) AS labels,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM detected_anomalies x
           WHERE x.detector = d.detector AND x.anomaly_type = l.anomaly_type
             AND x.entity_id = l.entity_id
             AND x.event_ts >= l.start_ts AND x.event_ts < l.end_ts)) AS caught
FROM anomaly_labels l
CROSS JOIN (SELECT DISTINCT detector FROM detected_anomalies) d
GROUP BY d.detector, l.anomaly_type
"""

PRECISION_SQL = """
SELECT x.detector, x.anomaly_type, count(*) AS detections,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM anomaly_labels l
           WHERE l.anomaly_type = x.anomaly_type AND l.entity_id = x.entity_id
             AND x.event_ts >= l.start_ts AND x.event_ts < l.end_ts)) AS correct
FROM detected_anomalies x
GROUP BY x.detector, x.anomaly_type
"""


def score() -> pd.DataFrame:
    """Return one row per detector and anomaly type with recall, precision and F1."""
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        recall = pd.read_sql(text(RECALL_SQL), conn)
        precision = pd.read_sql(text(PRECISION_SQL), conn)
    df = recall.merge(precision, on=["detector", "anomaly_type"], how="left").fillna(0)
    df["recall_pct"] = (100 * df["caught"] / df["labels"]).round(1)
    df["precision_pct"] = (100 * df["correct"] / df["detections"].where(df["detections"] > 0)).round(1)
    df["f1_pct"] = (
        2 * df["recall_pct"] * df["precision_pct"] / (df["recall_pct"] + df["precision_pct"])
    ).round(1)
    return df.fillna(0).sort_values(["anomaly_type", "detector"]).reset_index(drop=True)


def main() -> None:
    """Print the scores and save them to docs/anomaly_scores.csv."""
    df = score()
    print(df.to_string(index=False))
    out = config.PROJECT_ROOT / "docs" / "anomaly_scores.csv"
    Path(out.parent).mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()