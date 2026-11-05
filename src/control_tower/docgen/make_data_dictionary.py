"""Generate docs/data_dictionary.md from the live database.

Column names, types, nullability, primary keys and foreign keys come from information_schema,
so they cannot drift from the real schema. Table descriptions and notes on columns that are
not self-explanatory are written by hand below. Re-run after any schema change.
"""
import logging
from datetime import date

from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TABLES = {
    "products": ("real + simulated", "One row per product (118). Names, categories and prices are real; supplier_id is assigned at random by make_suppliers."),
    "suppliers": ("simulated", "Eight fictional suppliers with different reliability and lead times."),
    "orders": ("real + simulated", "One row per order line. Rows with order_item_id of 100,000,000 or more are injected copies that create demand spikes; all other rows are real DataCo orders."),
    "shipments": ("real", "One row per real order line: scheduled versus actual shipping days."),
    "supplier_deliveries": ("simulated", "Restock orders placed by the inventory simulation, with expected and actual arrival."),
    "inventory_snapshots": ("simulated", "Daily stock level per product, produced by replaying demand against a reorder rule."),
    "anomaly_labels": ("simulated", "The answer key: injected demand spikes and supplier delays. The detectors never read this table; it is used only to score them."),
    "detected_anomalies": ("derived", "Everything the detectors flagged."),
    "demand_forecasts": ("derived", "Prophet backtest results next to the naive baseline and real sales, for the products and test days used in the accuracy measurement."),
    "stock_risk": ("derived", "Current stock-out risk per product at the replay clock: forecast demand against stock and incoming deliveries."),
    "stock_forecast_daily": ("derived", "Prophet's expected demand for each of the next 14 days per product; input to the what-if view."),
    "replay_state": ("config", "Single row holding the replay clock."),
    "pipeline_runs": ("derived", "One row per hourly refresh run."),
    "alert_config": ("config", "Alert rules and thresholds. Edit a row to change an alert, with no code change."),
    "alert_log": ("derived", "Every alert that was raised, with Slack and email delivery status. Also used to avoid sending the same alert twice."),
}

VIEWS = {
    "v_kpi_stockout_daily": "KPI 1. Per day: products tracked, products at zero stock, stock-out rate. Only days before the replay clock.",
    "v_kpi_ontime_daily": "KPI 2. Per day and shipping mode: shipments, on-time shipments, on-time rate.",
    "v_kpi_supplier_leadtime": "KPI 3. Per supplier and month: deliveries, average lead time, average days late. Only deliveries that arrived before the replay clock.",
    "v_kpi_days_of_inventory": "KPI 4. Latest stock per product divided by the average daily demand of the last 14 days.",
    "v_stock_risk": "stock_risk with product and supplier names, for the dashboards.",
    "v_detector_scores": "Recall and precision of each detector against anomaly_labels.",
    "v_whatif_stockout": "What-if: stock-out day per product for each supplier delay of 0, 3, 5, 7, 10 or 14 days. A delay of 0 reproduces stock_risk.",
}

COLUMN_NOTES = {
    ("orders", "order_item_id"): "Unique id of the order line. 100,000,000 or more means an injected spike copy.",
    ("orders", "market"): "DataCo sales market.",
    ("orders", "loaded_at"): "When the row was loaded into Postgres.",
    ("shipments", "shipped_ts"): "Shipping date from DataCo.",
    ("shipments", "days_scheduled"): "Days the shipment was scheduled to take.",
    ("shipments", "days_real"): "Days it actually took.",
    ("shipments", "late_delivery_risk"): "DataCo's own late-delivery flag, copied as is.",
    ("shipments", "is_late"): "Generated column: true when days_real is greater than days_scheduled. The on-time KPI uses it.",
    ("suppliers", "reliability_score"): "0 to 1. Chance that a delivery arrives without a random extra delay.",
    ("suppliers", "base_lead_time_days"): "Typical days from restock order to arrival.",
    ("suppliers", "lead_time_stddev"): "Spread (standard deviation) of the lead time in days.",
    ("supplier_deliveries", "expected_ts"): "ordered_ts plus the supplier's base lead time.",
    ("supplier_deliveries", "received_ts"): "Actual arrival. Empty if it arrives after the end of the data.",
    ("inventory_snapshots", "market"): "Always ALL: one network-wide stock per product.",
    ("inventory_snapshots", "on_hand"): "Units in stock at the end of the day.",
    ("inventory_snapshots", "on_order"): "Units ordered from the supplier and not yet arrived.",
    ("inventory_snapshots", "reorder_point"): "Stock level (on hand plus on order) at which a restock order is placed.",
    ("anomaly_labels", "entity_id"): "product_id for demand spikes, supplier_id for supplier delays (see entity_type).",
    ("anomaly_labels", "start_ts"): "Start of the anomaly window.",
    ("anomaly_labels", "end_ts"): "End of the window (exclusive).",
    ("anomaly_labels", "magnitude"): "Demand spike: the multiplier (3 to 5). Supplier delay: extra days late.",
    ("detected_anomalies", "detector"): "zscore, isolation_forest or robust_zscore.",
    ("detected_anomalies", "entity_id"): "product_id or supplier_id, depending on entity_type.",
    ("detected_anomalies", "event_ts"): "Day of the flagged demand, or the order day of the flagged delivery.",
    ("detected_anomalies", "score"): "The detector's own score. Scales differ between detectors.",
    ("detected_anomalies", "detected_at"): "When the detector run saved this row.",
    ("demand_forecasts", "yhat"): "Prophet's expected units for the day.",
    ("demand_forecasts", "yhat_lower"): "Lower end of Prophet's prediction interval.",
    ("demand_forecasts", "yhat_upper"): "Upper end of Prophet's prediction interval.",
    ("demand_forecasts", "naive"): "Naive baseline: the last training week repeated.",
    ("demand_forecasts", "actual_real"): "Units really sold (injected spike copies excluded). Used for scoring.",
    ("demand_forecasts", "actual_total"): "Units sold including injected spike copies.",
    ("stock_risk", "as_of_ts"): "Replay clock when the row was calculated.",
    ("stock_risk", "incoming_14d"): "Units from deliveries arriving in the next 14 days.",
    ("stock_risk", "forecast_14d"): "Prophet's expected demand over the next 14 days.",
    ("stock_risk", "forecast_14d_high"): "The same, using Prophet's upper bound.",
    ("stock_risk", "days_of_cover"): "on_hand divided by the average expected daily demand.",
    ("stock_risk", "stockout_day_expected"): "First day (1 = replay-clock day) stock reaches zero with expected demand. Empty if not within 14 days.",
    ("stock_risk", "stockout_day_high"): "The same with the high-demand forecast.",
    ("stock_risk", "risk_level"): "high if the expected stock-out is within 7 days; medium if later or only at high demand; low if neither.",
    ("stock_forecast_daily", "day_no"): "Day 1 is the replay-clock day, up to day 14.",
    ("replay_state", "id"): "Always 1: this is a single-row table.",
    ("replay_state", "watermark_ts"): "The replay clock. Every KPI view and the alert engine only see data before it.",
    ("replay_state", "slice_hours"): "How far the clock moves in each run.",
    ("pipeline_runs", "started_at"): "Real time the run started.",
    ("pipeline_runs", "finished_at"): "Real time the run finished.",
    ("pipeline_runs", "from_ts"): "Start of the slice of data covered by the run.",
    ("pipeline_runs", "to_ts"): "End of that slice (the new clock position).",
    ("pipeline_runs", "orders_seen"): "Order lines inside the slice.",
    ("alert_config", "comparison"): "gt = alert when the metric is above the threshold; lt = alert when below.",
    ("alert_config", "min_volume"): "Minimum daily demand for the product rule. Empty for other rules.",
    ("alert_config", "severity"): "warning or critical.",
    ("alert_config", "cooldown_hours"): "Hours before the same rule and entity can alert again.",
    ("alert_log", "entity_key"): "What the alert is about: global, supplier:ID or product:ID.",
    ("alert_log", "data_ts"): "Date of the data that crossed the threshold.",
    ("alert_log", "fired_at"): "Real time the alert was recorded. The cooldown uses it.",
    ("alert_log", "slack_status"): "pending, sent or failed.",
    ("alert_log", "email_status"): "pending, sent or failed.",
    ("v_kpi_stockout_daily", "stockout_rate_pct"): "Share of tracked products with zero stock that day, in percent.",
    ("v_kpi_ontime_daily", "ontime_rate_pct"): "Share of shipments not late, in percent. To combine days, divide summed on_time by summed shipments instead of averaging this column.",
    ("v_kpi_supplier_leadtime", "avg_lead_time_days"): "Average days from restock order to arrival.",
    ("v_kpi_supplier_leadtime", "avg_days_late"): "Average days between expected and actual arrival.",
    ("v_kpi_days_of_inventory", "daily_demand_14d"): "Average units sold per day over the 14 days before the replay clock.",
    ("v_kpi_days_of_inventory", "days_of_inventory"): "on_hand divided by daily_demand_14d. Empty when there were no sales in the last 14 days.",
    ("v_whatif_stockout", "delay_days"): "Assumed delay applied to every incoming delivery: 0, 3, 5, 7, 10 or 14.",
    ("v_whatif_stockout", "stockout_day"): "First day (1 = replay-clock day) stock reaches zero. Empty if not within 14 days.",
    ("v_whatif_stockout", "baseline_stockout_day"): "stockout_day with a delay of 0 (equals stock_risk.stockout_day_expected).",
    ("v_whatif_stockout", "days_earlier"): "How many days earlier the product runs out than with no delay (no stock-out counts as day 15).",
    ("v_whatif_stockout", "whatif_risk"): "high if stockout_day is 7 or less, medium if later, low if none.",
    ("v_detector_scores", "recall_pct"): "Share of labeled anomalies caught.",
    ("v_detector_scores", "precision_pct"): "Share of detections inside a labeled window. Understated; see results.md.",
}

COLUMNS_SQL = """
SELECT c.table_name, c.column_name, c.data_type, c.numeric_precision, c.numeric_scale,
       c.is_nullable, t.table_type
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema = 'public'
ORDER BY c.table_name, c.ordinal_position
"""

PK_SQL = """
SELECT tc.table_name, kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
"""

FK_SQL = """
SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
"""


def fmt_type(row) -> str:
    """Short, readable column type."""
    data_type = row["data_type"]
    if data_type == "numeric" and row["numeric_precision"] is not None:
        return f"numeric({row['numeric_precision']},{row['numeric_scale']})"
    short = {
        "timestamp without time zone": "timestamp",
        "timestamp with time zone": "timestamptz",
        "double precision": "float",
    }
    return short.get(data_type, data_type)


def ordered(names: list[str], known: dict) -> list[str]:
    """Known names in the order they are listed above, then any others alphabetically."""
    order = list(known)
    return sorted(names, key=lambda n: (order.index(n) if n in order else len(order), n))


def column_table(name: str, rows: list, pks: set, fks: dict) -> list[str]:
    """Markdown table of one table's or view's columns."""
    lines = ["| Column | Type | Null | Key | Notes |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        col = r["column_name"]
        keys = []
        if (name, col) in pks:
            keys.append("PK")
        if (name, col) in fks:
            keys.append(f"FK to {fks[(name, col)]}")
        null = "yes" if r["is_nullable"] == "YES" else "no"
        note = COLUMN_NOTES.get((name, col), "")
        lines.append(f"| {col} | {fmt_type(r)} | {null} | {', '.join(keys)} | {note} |")
    return lines


def main() -> None:
    """Read the schema from the database and write docs/data_dictionary.md."""
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        rows = conn.execute(text(COLUMNS_SQL)).mappings().all()
        pks = {(r["table_name"], r["column_name"]) for r in conn.execute(text(PK_SQL)).mappings()}
        fks = {
            (r["table_name"], r["column_name"]): f"{r['ref_table']}.{r['ref_column']}"
            for r in conn.execute(text(FK_SQL)).mappings()
        }
        by_name: dict[str, list] = {}
        kind: dict[str, str] = {}
        for r in rows:
            by_name.setdefault(r["table_name"], []).append(r)
            kind[r["table_name"]] = r["table_type"]
        counts = {
            n: conn.execute(text(f'SELECT count(*) FROM "{n}"')).scalar_one()
            for n, k in kind.items()
            if k == "BASE TABLE"
        }

    tables = ordered([n for n, k in kind.items() if k == "BASE TABLE"], TABLES)
    views = ordered([n for n, k in kind.items() if k == "VIEW"], VIEWS)
    missing = [n for n in tables if n not in TABLES] + [n for n in views if n not in VIEWS]
    if missing:
        log.warning("No description for: %s", ", ".join(missing))

    out = [
        "# Data dictionary",
        "",
        f"Generated on {date.today().isoformat()} by `python -m control_tower.docgen.make_data_dictionary` "
        "from the live database. Do not edit by hand: change the descriptions in the script and run it again.",
        "",
        "Source: **real** = from the DataCo CSV, **simulated** = created by the scripts in `simulate/`, "
        "**derived** = calculated by the pipeline, **config** = settings.",
        "",
        f"{len(tables)} tables and {len(views)} views. Row counts are from the generation date.",
        "",
        "## Tables",
        "",
    ]
    for n in tables:
        source, desc = TABLES.get(n, ("unknown", "(no description yet)"))
        out += [f"### `{n}`", "", desc, "", f"Source: {source}. Rows: {counts[n]:,}.", ""]
        out += column_table(n, by_name[n], pks, fks) + [""]
    out += ["## Views", ""]
    for n in views:
        out += [f"### `{n}`", "", VIEWS.get(n, "(no description yet)"), ""]
        out += column_table(n, by_name[n], pks, fks) + [""]

    path = config.PROJECT_ROOT / "docs" / "data_dictionary.md"
    path.write_text("\n".join(out), encoding="utf-8")
    log.info("Wrote %s (%d tables, %d views)", path, len(tables), len(views))


if __name__ == "__main__":
    main()