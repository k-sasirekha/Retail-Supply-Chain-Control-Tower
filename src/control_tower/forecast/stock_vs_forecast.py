"""Compare Prophet's next-14-day demand forecast with current stock.

The replay clock (replay_state.watermark_ts) is treated as "now". Prophet is trained only
on real demand before the clock. Stock comes from the latest snapshot before the clock, and
deliveries that are ordered but not yet received are added on the day they arrive.
Re-running replaces the contents of stock_risk.
"""
import logging
import time

import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
for noisy in ("cmdstanpy", "prophet"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

INJECTED_ID_START = 100_000_000
HORIZON_DAYS = 14
N_PRODUCTS = 30
MIN_HISTORY_DAYS = 180
RECENT_DAYS = 90
MIN_RECENT_UNITS = 30
HIGH_RISK_DAYS = 7


def pick_products(daily: pd.DataFrame, clock_day: pd.Timestamp) -> list[int]:
    """Best recent sellers that have enough history, using only data before the clock."""
    stats = daily.groupby("product_id").agg(first_day=("day", "min"))
    recent = daily[daily["day"] >= clock_day - pd.Timedelta(days=RECENT_DAYS)]
    stats["recent_units"] = recent.groupby("product_id")["qty"].sum()
    stats["recent_units"] = stats["recent_units"].fillna(0)
    enough_history = (clock_day - stats["first_day"]).dt.days >= MIN_HISTORY_DAYS
    eligible = stats[enough_history & (stats["recent_units"] >= MIN_RECENT_UNITS)]
    return [int(p) for p in eligible.sort_values("recent_units", ascending=False).head(N_PRODUCTS).index]


def forecast_next(grp: pd.DataFrame, clock_day: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """Train Prophet on real demand before the clock; return (expected, high) per future day."""
    days = pd.date_range(grp["day"].min(), clock_day - pd.Timedelta(days=1))
    qty = grp.set_index("day")["qty"].astype(float).reindex(days, fill_value=0.0)
    model = Prophet(weekly_seasonality=True, yearly_seasonality=True, daily_seasonality=False)
    model.fit(pd.DataFrame({"ds": qty.index, "y": qty.to_numpy()}))
    future = pd.DataFrame({"ds": pd.date_range(clock_day, periods=HORIZON_DAYS)})
    pred = model.predict(future)
    return pred["yhat"].clip(lower=0).to_numpy(), pred["yhat_upper"].clip(lower=0).to_numpy()


def first_stockout(on_hand: int, arrivals: np.ndarray, demand: np.ndarray) -> int | None:
    """First day (1 = clock day) on which projected stock reaches zero, or None."""
    stock = on_hand + np.cumsum(arrivals) - np.cumsum(demand)
    hits = np.nonzero(stock <= 0)[0]
    return int(hits[0]) + 1 if len(hits) else None


def risk_level(expected: int | None, high: int | None) -> str:
    """High if the expected stock-out is within a week; medium if later or only at high demand."""
    if expected is not None and expected <= HIGH_RISK_DAYS:
        return "high"
    if expected is not None or high is not None:
        return "medium"
    return "low"


def main() -> None:
    """Build the stock_risk table from the forecast and current stock."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        clock = pd.Timestamp(conn.execute(text("SELECT watermark_ts FROM replay_state WHERE id = 1")).scalar_one())
        clock_day = clock.normalize()
        daily = pd.read_sql(
            text(
                "SELECT product_id, CAST(order_ts AS date) AS day, sum(quantity) AS qty FROM orders "
                "WHERE order_item_id < :inj AND order_ts < :clock "
                "GROUP BY product_id, CAST(order_ts AS date)"
            ),
            conn, params={"inj": INJECTED_ID_START, "clock": clock},
        )
        stock = pd.read_sql(
            text(
                "SELECT DISTINCT ON (product_id) product_id, on_hand, on_order FROM inventory_snapshots "
                "WHERE snapshot_ts < :clock ORDER BY product_id, snapshot_ts DESC"
            ),
            conn, params={"clock": clock},
        ).set_index("product_id")
        incoming = pd.read_sql(
            text(
                "SELECT product_id, received_ts, quantity FROM supplier_deliveries "
                "WHERE ordered_ts < :clock AND received_ts >= :clock"
            ),
            conn, params={"clock": clock},
        )
    daily["day"] = pd.to_datetime(daily["day"])
    incoming["received_ts"] = pd.to_datetime(incoming["received_ts"])

    products = [p for p in pick_products(daily, clock_day) if p in stock.index]
    if not products:
        log.error("No eligible products at clock %s.", clock)
        return
    log.info("Stock risk for %d products as of %s", len(products), clock)

    rows = []
    for pid in products:
        expected, high = forecast_next(daily[daily["product_id"] == pid], clock_day)
        arrivals = np.zeros(HORIZON_DAYS)
        for received, qty in incoming.loc[incoming["product_id"] == pid, ["received_ts", "quantity"]].itertuples(index=False):
            offset = (received.normalize() - clock_day).days
            if 0 <= offset < HORIZON_DAYS:
                arrivals[offset] += qty
        on_hand = int(stock.loc[pid, "on_hand"])
        avg_daily = float(expected.mean())
        out_expected = first_stockout(on_hand, arrivals, expected)
        out_high = first_stockout(on_hand, arrivals, high)
        rows.append(
            {
                "product_id": pid,
                "as_of_ts": clock,
                "on_hand": on_hand,
                "on_order": int(stock.loc[pid, "on_order"]),
                "incoming_14d": int(arrivals.sum()),
                "forecast_14d": round(float(expected.sum()), 1),
                "forecast_14d_high": round(float(high.sum()), 1),
                "days_of_cover": round(on_hand / avg_daily, 1) if avg_daily >= 0.01 else None,
                "stockout_day_expected": out_expected,
                "stockout_day_high": out_high,
                "risk_level": risk_level(out_expected, out_high),
            }
        )

    result = pd.DataFrame(rows)
    for col in ("stockout_day_expected", "stockout_day_high"):
        result[col] = result[col].astype("Int64")
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE stock_risk"))
    result.to_sql("stock_risk", engine, if_exists="append", index=False)
    counts = result["risk_level"].value_counts().to_dict()
    log.info("Stored %d rows %s in %.1fs.", len(result), counts, time.perf_counter() - started)


if __name__ == "__main__":
    main()