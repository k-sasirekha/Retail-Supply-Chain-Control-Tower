"""Save Prophet's day-by-day expected demand for the products in stock_risk.

Uses the same clock and the same forecasting code as stock_vs_forecast.py, so the
what-if view starts from numbers that match the stock_risk table.
Re-running replaces the contents of stock_forecast_daily.
"""
import logging
import time

import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config
from control_tower.forecast.stock_vs_forecast import HORIZON_DAYS, INJECTED_ID_START, forecast_next

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    """Forecast each stock_risk product again and store the 14 daily values."""
    started = time.perf_counter()
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        clock = pd.Timestamp(conn.execute(text("SELECT as_of_ts FROM stock_risk LIMIT 1")).scalar_one())
        product_ids = [int(r[0]) for r in conn.execute(text("SELECT product_id FROM stock_risk ORDER BY product_id"))]
        daily = pd.read_sql(
            text(
                "SELECT product_id, CAST(order_ts AS date) AS day, sum(quantity) AS qty FROM orders "
                "WHERE order_item_id < :inj AND order_ts < :clock "
                "GROUP BY product_id, CAST(order_ts AS date)"
            ),
            conn, params={"inj": INJECTED_ID_START, "clock": clock},
        )
    daily["day"] = pd.to_datetime(daily["day"])
    clock_day = clock.normalize()

    rows = []
    for pid in product_ids:
        expected, high = forecast_next(daily[daily["product_id"] == pid], clock_day)
        for i in range(HORIZON_DAYS):
            rows.append(
                {
                    "product_id": pid,
                    "day_no": i + 1,
                    "expected": round(float(expected[i]), 3),
                    "expected_high": round(float(high[i]), 3),
                }
            )

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE stock_forecast_daily"))
    pd.DataFrame(rows).to_sql("stock_forecast_daily", engine, if_exists="append", index=False)
    log.info("Stored %d daily values for %d products as of %s in %.1fs.", len(rows), len(product_ids), clock, time.perf_counter() - started)


if __name__ == "__main__":
    main()