"""Simulate supplier deliveries and daily inventory from the real orders.

Reads the labeled supplier-delay windows, so deliveries ordered inside a window
arrive extra late. Re-running replaces the old deliveries and snapshots.
"""
import logging
import math
import time

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SEED = 21
INJECTED_ID_START = 100_000_000
MARKET = "ALL"
SAFETY_DAYS = 3
COVER_DAYS = 14
UNRELIABLE_EXTRA_DAYS = (2, 7)  # random extra days, low end included, high end excluded
END_DAY = pd.Timestamp("2018-01-31")


def lead_time_days(supplier: dict, order_day: pd.Timestamp, windows: list, rng: np.random.Generator) -> int:
    """Actual days a delivery takes: normal noise, random lateness, labeled delay windows."""
    days = max(1, round(rng.normal(supplier["lead"], supplier["std"])))
    if rng.random() > supplier["rel"]:
        days += int(rng.integers(*UNRELIABLE_EXTRA_DAYS))
    for start, end, extra in windows:
        if start <= order_day < end:
            days += extra
    return int(days)


def simulate_product(
    product_id: int,
    supplier_id: int,
    supplier: dict,
    windows: list,
    series: pd.Series,
    base_demand: float,
    rng: np.random.Generator,
) -> tuple[list[dict], list[dict]]:
    """Replay one product day by day. Returns (deliveries, snapshots)."""
    lead = supplier["lead"]
    reorder_point = math.ceil(base_demand * (lead + SAFETY_DAYS))
    order_up_to = math.ceil(base_demand * (lead + COVER_DAYS))
    days = pd.date_range(series.index.min(), END_DAY)
    demand = series.reindex(days, fill_value=0).to_numpy()

    on_hand = order_up_to
    pipeline: list[tuple[pd.Timestamp, int]] = []
    deliveries: list[dict] = []
    snapshots: list[dict] = []

    for day, units in zip(days, demand):
        arrived = [p for p in pipeline if p[0] <= day]
        for item in arrived:
            on_hand += item[1]
            pipeline.remove(item)
        on_hand = max(0, on_hand - int(units))
        on_order = sum(q for _, q in pipeline)

        if on_hand + on_order <= reorder_point:
            qty = int(order_up_to - on_hand - on_order)
            arrival = day + pd.Timedelta(days=lead_time_days(supplier, day, windows, rng))
            pipeline.append((arrival, qty))
            on_order += qty
            deliveries.append(
                {
                    "supplier_id": supplier_id,
                    "product_id": product_id,
                    "ordered_ts": day,
                    "expected_ts": day + pd.Timedelta(days=lead),
                    "received_ts": arrival if arrival <= END_DAY else None,
                    "quantity": qty,
                }
            )
        snapshots.append(
            {
                "snapshot_ts": day,
                "product_id": product_id,
                "market": MARKET,
                "on_hand": int(on_hand),
                "on_order": int(on_order),
                "reorder_point": int(reorder_point),
            }
        )
    return deliveries, snapshots


def main() -> None:
    """Simulate every product and load deliveries and snapshots."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())
    rng = np.random.default_rng(SEED)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE supplier_deliveries, inventory_snapshots RESTART IDENTITY"))
        suppliers = {
            r[0]: {"rel": float(r[1]), "lead": int(r[2]), "std": float(r[3])}
            for r in conn.execute(
                text("SELECT supplier_id, reliability_score, base_lead_time_days, lead_time_stddev FROM suppliers")
            )
        }
        windows: dict[int, list] = {}
        for sid, start, end, mag in conn.execute(
            text("SELECT entity_id, start_ts, end_ts, magnitude FROM anomaly_labels WHERE anomaly_type = 'supplier_delay'")
        ):
            windows.setdefault(sid, []).append((pd.Timestamp(start), pd.Timestamp(end), int(float(mag))))
        product_supplier = {
            r[0]: r[1] for r in conn.execute(text("SELECT product_id, supplier_id FROM products"))
        }
        demand = pd.read_sql(
            text(
                "SELECT product_id, CAST(order_ts AS date) AS day, sum(quantity) AS qty, "
                "sum(quantity) FILTER (WHERE order_item_id < :inj) AS real_qty "
                "FROM orders GROUP BY product_id, CAST(order_ts AS date)"
            ),
            conn,
            params={"inj": INJECTED_ID_START},
        )

    demand["qty"] = demand["qty"].astype(int)
    demand["real_qty"] = demand["real_qty"].fillna(0).astype(int)
    all_deliveries: list[dict] = []
    all_snapshots: list[dict] = []

    for pid, grp in demand.groupby("product_id"):
        supplier_id = product_supplier.get(int(pid))
        if supplier_id is None:
            continue
        series = grp.set_index(pd.to_datetime(grp["day"]))["qty"]
        n_days = (END_DAY - series.index.min()).days + 1
        base_demand = max(grp["real_qty"].sum() / n_days, 0.5)  # real demand only, spikes excluded
        deliveries, snapshots = simulate_product(
            int(pid), int(supplier_id), suppliers[supplier_id],
            windows.get(supplier_id, []), series, base_demand, rng,
        )
        all_deliveries.extend(deliveries)
        all_snapshots.extend(snapshots)

    pd.DataFrame(all_deliveries).to_sql(
        "supplier_deliveries", engine, if_exists="append", index=False, chunksize=5000, method="multi"
    )
    pd.DataFrame(all_snapshots).to_sql(
        "inventory_snapshots", engine, if_exists="append", index=False, chunksize=5000, method="multi"
    )
    log.info(
        "Loaded %d deliveries and %d snapshots in %.1fs.",
        len(all_deliveries), len(all_snapshots), time.perf_counter() - started,
    )


if __name__ == "__main__":
    main()