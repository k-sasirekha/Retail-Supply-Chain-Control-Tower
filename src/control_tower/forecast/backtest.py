"""Backtest Prophet against a naive baseline on the top-selling products.

Trains on data up to TRAIN_END, forecasts the days after it, and stores the forecast
next to what really sold. Prophet is trained on real demand only (injected spikes excluded).
Re-running replaces the old results.
"""
import logging
import time

import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
for noisy in ("cmdstanpy", "prophet"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

INJECTED_ID_START = 100_000_000
TRAIN_END = pd.Timestamp("2017-10-31")
TEST_END = pd.Timestamp("2018-01-31")
N_PRODUCTS = 30
MIN_HISTORY_DAYS = 365


def load_daily(engine: Engine) -> pd.DataFrame:
    """Units sold per product per day: real only, and total including injected spikes."""
    sql = text(
        "SELECT product_id, CAST(order_ts AS date) AS day, "
        "sum(quantity) FILTER (WHERE order_item_id < :inj) AS real_qty, "
        "sum(quantity) AS total_qty "
        "FROM orders GROUP BY product_id, CAST(order_ts AS date)"
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"inj": INJECTED_ID_START})
    df["day"] = pd.to_datetime(df["day"])
    df[["real_qty", "total_qty"]] = df[["real_qty", "total_qty"]].fillna(0).astype(float)
    return df


def pick_products(daily: pd.DataFrame) -> list[int]:
    """The best sellers (real units before TRAIN_END) with at least a year of history."""
    train = daily[daily["day"] <= TRAIN_END]
    stats = train.groupby("product_id").agg(units=("real_qty", "sum"), first_day=("day", "min"))
    eligible = stats[(TRAIN_END - stats["first_day"]).dt.days >= MIN_HISTORY_DAYS]
    return [int(p) for p in eligible.sort_values("units", ascending=False).head(N_PRODUCTS).index]


def forecast_one(pid: int, grp: pd.DataFrame) -> pd.DataFrame:
    """Fit Prophet on one product and forecast the test period."""
    days = pd.date_range(grp["day"].min(), TEST_END)
    g = grp.set_index("day")[["real_qty", "total_qty"]].reindex(days, fill_value=0.0)
    train = g.loc[:TRAIN_END]
    history = pd.DataFrame({"ds": train.index, "y": train["real_qty"].to_numpy()})

    model = Prophet(weekly_seasonality=True, yearly_seasonality=True, daily_seasonality=False)
    model.fit(history)

    test_days = days[days > TRAIN_END]
    pred = model.predict(pd.DataFrame({"ds": test_days}))

    # Naive baseline: repeat the last 7 training days, week after week
    last_week = train["real_qty"].to_numpy()[-7:]
    naive = np.tile(last_week, int(np.ceil(len(test_days) / 7)))[: len(test_days)]
    test = g.loc[test_days]
    return pd.DataFrame(
        {
            "product_id": pid,
            "day": test_days,
            "yhat": pred["yhat"].clip(lower=0).round(2).to_numpy(),
            "yhat_lower": pred["yhat_lower"].clip(lower=0).round(2).to_numpy(),
            "yhat_upper": pred["yhat_upper"].clip(lower=0).round(2).to_numpy(),
            "naive": naive,
            "actual_real": test["real_qty"].to_numpy(),
            "actual_total": test["total_qty"].to_numpy(),
        }
    )


def main() -> None:
    """Forecast every chosen product and store the results."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())
    daily = load_daily(engine)
    products = pick_products(daily)
    log.info("Forecasting %d products", len(products))

    frames = []
    for i, pid in enumerate(products, 1):
        frames.append(forecast_one(pid, daily[daily["product_id"] == pid]))
        log.info("%d/%d: product %d done", i, len(products), pid)

    result = pd.concat(frames, ignore_index=True)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE demand_forecasts"))
    result.to_sql("demand_forecasts", engine, if_exists="append", index=False, chunksize=5000, method="multi")
    log.info("Stored %d rows for %d products in %.1fs.", len(result), len(products), time.perf_counter() - started)


if __name__ == "__main__":
    main()