"""Inject labeled demand spikes by duplicating real order lines.

The original DataCo rows are never changed. Injected rows get order_item_id
values of 100,000,000 and above, so they can be told apart (and removed) later.
"""
import logging

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SEED = 7
N_SPIKES = 15
TOP_PRODUCTS = 20
MIN_LINES_IN_WINDOW = 10
INJECTED_ID_START = 100_000_000
FACTORS = [3, 4, 5]
DURATIONS_DAYS = [2, 3, 4]
EARLIEST = pd.Timestamp("2015-03-01")
LATEST = pd.Timestamp("2017-12-01")

ORDER_COLUMNS = (
    "order_item_id, order_id, order_ts, product_id, market, order_region, "
    "order_country, quantity, unit_price, discount, sales, order_status"
)


def find_window(
    prod: pd.DataFrame, rng: np.random.Generator
) -> tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame] | None:
    """Pick a random multi-day window in which the product has enough real orders."""
    span_days = (LATEST - EARLIEST).days
    for _ in range(200):
        start = EARLIEST + pd.Timedelta(days=int(rng.integers(0, span_days)))
        end = start + pd.Timedelta(days=int(rng.choice(DURATIONS_DAYS)))
        window = prod[(prod["order_ts"] >= start) & (prod["order_ts"] < end)]
        if len(window) >= MIN_LINES_IN_WINDOW:
            return start, end, window
    return None


def main() -> None:
    """Remove old injected rows, then inject new spikes and record the labels."""
    engine = create_engine(config.database_url())
    rng = np.random.default_rng(SEED)

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM orders WHERE order_item_id >= :start"),
            {"start": INJECTED_ID_START},
        )
        conn.execute(text("DELETE FROM anomaly_labels WHERE anomaly_type = 'demand_spike'"))
        top = [
            int(r[0])
            for r in conn.execute(
                text("SELECT product_id FROM orders GROUP BY product_id ORDER BY count(*) DESC LIMIT :n"),
                {"n": TOP_PRODUCTS},
            )
        ]
        id_list = ",".join(str(p) for p in top)  # ints from our own database, safe to inline
        orders = pd.read_sql(
            text(f"SELECT {ORDER_COLUMNS} FROM orders WHERE product_id IN ({id_list})"), conn
        )

    chosen = [int(p) for p in rng.choice(top, size=N_SPIKES, replace=False)]
    next_id = INJECTED_ID_START
    extras: list[pd.DataFrame] = []
    labels: list[dict] = []

    for pid in chosen:
        found = find_window(orders[orders["product_id"] == pid], rng)
        if found is None:
            log.warning("No suitable window for product %d, skipped", pid)
            continue
        start, end, window = found
        factor = int(rng.choice(FACTORS))
        extra = pd.concat([window] * (factor - 1), ignore_index=True)
        extra["order_item_id"] = np.arange(next_id, next_id + len(extra))
        next_id += len(extra)
        extras.append(extra)
        labels.append(
            {
                "anomaly_type": "demand_spike",
                "entity_type": "product",
                "entity_id": pid,
                "start_ts": start,
                "end_ts": end,
                "magnitude": float(factor),
            }
        )
        log.info("Product %d: %dx spike from %s to %s (+%d lines)", pid, factor, start.date(), end.date(), len(extra))

    if not extras:
        log.error("No spikes were created.")
        return

    pd.concat(extras, ignore_index=True).to_sql(
        "orders", engine, if_exists="append", index=False, chunksize=5000, method="multi"
    )
    pd.DataFrame(labels).to_sql("anomaly_labels", engine, if_exists="append", index=False)
    log.info("Injected %d spikes.", len(labels))


if __name__ == "__main__":
    main()