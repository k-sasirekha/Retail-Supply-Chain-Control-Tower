"""Measure query and pipeline performance and write docs/results.md.

Everything that can be measured live is measured here. Timings from earlier one-off runs
(data load, simulation, detectors, forecasting) are listed in MEASURED_EARLIER, because
those scripts are not re-run here.
"""
import logging
import platform
import statistics
import time
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPEATS = 7
VIEWS = [
    "v_kpi_stockout_daily",
    "v_kpi_ontime_daily",
    "v_kpi_supplier_leadtime",
    "v_kpi_days_of_inventory",
    "v_stock_risk",
    "v_detector_scores",
    "v_whatif_stockout",
]
TABLES = [
    "products", "suppliers", "orders", "shipments", "supplier_deliveries",
    "inventory_snapshots", "anomaly_labels", "detected_anomalies", "demand_forecasts",
    "stock_risk", "alert_log",
]
MEASURED_EARLIER = [
    ("Load 180,519 orders into Postgres", "37.8 s"),
    ("Load 180,519 shipments into Postgres", "19.5 s"),
    ("Simulate 4,344 deliveries and 73,393 daily inventory snapshots", "9.0 s"),
    ("Anomaly detectors v1 (z-score and Isolation Forest, 4 detectors)", "1.7 s"),
    ("Robust z-score demand detector (v2)", "3.5 s"),
    ("Prophet backtest, 14 products, 92 test days", "5.6 s"),
    ("Stock risk (forecast vs stock), 30 products", "11.3 s"),
    ("Full hourly DAG run (4 tasks, in Airflow)", "about 5 s"),
    ("Unit tests (19)", "2 to 5 s"),
]
INDEX_QUERY = (
    "SELECT sum(quantity) FROM orders WHERE product_id = :p "
    "AND order_ts >= '2016-01-01' AND order_ts < '2016-04-01'"
)


def median_ms(conn: Connection, sql: str, params: dict | None = None) -> tuple[float, int]:
    """Run a query REPEATS times; return (median milliseconds, rows returned)."""
    times: list[float] = []
    rows = 0
    for _ in range(REPEATS):
        start = time.perf_counter()
        rows = len(conn.execute(text(sql), params or {}).fetchall())
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), rows


def scan_type(conn: Connection, sql: str, params: dict) -> str:
    """Whether Postgres reads the whole table or uses an index for this query."""
    plan = "\n".join(r[0] for r in conn.execute(text("EXPLAIN " + sql), params))
    return "sequential scan (whole table)" if "Seq Scan" in plan else "index scan"


def index_effect(engine: Engine) -> dict:
    """Time one query with the orders indexes, then without them (rolled back afterwards)."""
    with engine.connect() as conn:
        pid = conn.execute(
            text("SELECT product_id FROM orders GROUP BY product_id ORDER BY count(*) DESC LIMIT 1")
        ).scalar_one()
        with_ms, _ = median_ms(conn, INDEX_QUERY, {"p": pid})
        with_scan = scan_type(conn, INDEX_QUERY, {"p": pid})
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("DROP INDEX idx_orders_product_ts"))
            conn.execute(text("DROP INDEX idx_orders_ts"))
            without_ms, _ = median_ms(conn, INDEX_QUERY, {"p": pid})
            without_scan = scan_type(conn, INDEX_QUERY, {"p": pid})
        finally:
            trans.rollback()
    return {"with_ms": with_ms, "without_ms": without_ms, "with_scan": with_scan, "without_scan": without_scan}


def md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame as a markdown table."""
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    divider = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([header, divider, *rows])


def main() -> None:
    """Measure everything and write docs/results.md."""
    engine = create_engine(config.database_url())
    docs = config.PROJECT_ROOT / "docs"
    with engine.connect() as conn:
        clock = conn.execute(text("SELECT watermark_ts FROM replay_state WHERE id = 1")).scalar_one()
        counts = pd.DataFrame(
            [(t, f"{conn.execute(text(f'SELECT count(*) FROM {t}')).scalar_one():,}") for t in TABLES],
            columns=["table", "rows"],
        )
        timing_rows = []
        for view in VIEWS:
            ms, n = median_ms(conn, f"SELECT * FROM {view}")
            timing_rows.append((view, n, round(ms, 1)))
            log.info("%-26s %6d rows %8.1f ms", view, n, ms)
        runs = conn.execute(
            text(
                "SELECT count(*), round(avg(EXTRACT(epoch FROM (finished_at - started_at)) * 1000)::numeric, 1) "
                "FROM pipeline_runs WHERE status = 'success'"
            )
        ).one()
        detectors = pd.read_sql(
            text(
                "SELECT detector, anomaly_type, labels, caught, detections, correct, recall_pct, precision_pct "
                "FROM v_detector_scores ORDER BY anomaly_type, detector"
            ),
            conn,
        )
    views_df = pd.DataFrame(timing_rows, columns=["view", "rows returned", f"median ms ({REPEATS} runs)"])
    idx = index_effect(engine)
    log.info("Index effect: %.1f ms with, %.1f ms without", idx["with_ms"], idx["without_ms"])

    overall = pd.read_csv(docs / "forecast_scores_overall.csv", index_col=0).reset_index()
    overall = overall.rename(columns={"index": "model"})
    by_product = pd.read_csv(docs / "forecast_scores_by_product.csv")
    wins = int((by_product["prophet_rmse"] < by_product["naive_rmse"]).sum())

    lines = [
        "# Results",
        "",
        f"Generated on {date.today().isoformat()} by `python -m control_tower.benchmarks.run_benchmarks`.",
        f"Machine: {platform.platform()}, Python {platform.python_version()}, Postgres 15 in Docker (about 6 GB for Docker).",
        f"Replay clock at measurement time: {clock}.",
        "",
        "## Data volumes", "", md_table(counts), "",
        "## Query performance (views read by the Superset dashboards)", "", md_table(views_df), "",
        "## Index effect",
        "",
        "Query: units sold of the best-selling product over three months, on the orders table.",
        "",
        f"- With the indexes `idx_orders_product_ts` and `idx_orders_ts`: {idx['with_ms']:.1f} ms ({idx['with_scan']})",
        f"- Without them: {idx['without_ms']:.1f} ms ({idx['without_scan']})",
        "",
        "## Pipeline",
        "",
        f"- Successful hourly runs recorded so far: {runs[0]}",
        "- Time per run: about 1 to 1.5 s per task and about 5 s for the whole DAG, measured in Airflow.",
        "",
        "## Timings from earlier runs (taken from the run logs)", "",
        md_table(pd.DataFrame(MEASURED_EARLIER, columns=["step", "time"])), "",
        "## Anomaly detection against the labeled anomalies", "", md_table(detectors), "",
        "Notes: precision is understated. Unreliable suppliers are late at random by design, "
        "and those real late deliveries count as false positives because only the injected delays are labeled. "
        "Demand spikes may be missed on products with little sales history (not checked separately).",
        "",
        "## Forecast accuracy (backtest: train to 2017-06-30, test 2017-07-01 to 2017-09-30, 14 products)",
        "",
        md_table(overall), "",
        f"Prophet beats the naive baseline (RMSE) on {wins} of {len(by_product)} products.",
        "",
    ]
    out = docs / "results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out)


if __name__ == "__main__":
    main()