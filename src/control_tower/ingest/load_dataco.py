"""Load the DataCo CSV into the products, orders and shipments tables."""
import logging
import time

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def read_raw_csv() -> pd.DataFrame:
    """Read the raw CSV (latin-1 encoded) and parse the US-style dates."""
    df = pd.read_csv(config.RAW_CSV_PATH, encoding="latin-1")
    df["order_ts"] = pd.to_datetime(df["order date (DateOrders)"], format="%m/%d/%Y %H:%M")
    df["shipped_ts"] = pd.to_datetime(df["shipping date (DateOrders)"], format="%m/%d/%Y %H:%M")
    log.info("Read %d rows. Order dates: %s to %s", len(df), df["order_ts"].min(), df["order_ts"].max())
    return df


def build_products(df: pd.DataFrame) -> pd.DataFrame:
    """One row per product (supplier_id is filled later by the simulator)."""
    products = df[
        ["Product Card Id", "Product Name", "Category Id", "Category Name",
         "Department Name", "Product Price"]
    ].drop_duplicates(subset="Product Card Id")
    products.columns = [
        "product_id", "product_name", "category_id", "category_name",
        "department_name", "unit_price",
    ]
    return products


def build_orders(df: pd.DataFrame) -> pd.DataFrame:
    """One row per order line, keeping only the columns we need (no personal data)."""
    orders = df[
        ["Order Item Id", "Order Id", "order_ts", "Product Card Id", "Market",
         "Order Region", "Order Country", "Order Item Quantity",
         "Order Item Product Price", "Order Item Discount", "Sales", "Order Status"]
    ].copy()
    orders.columns = [
        "order_item_id", "order_id", "order_ts", "product_id", "market",
        "order_region", "order_country", "quantity", "unit_price",
        "discount", "sales", "order_status",
    ]
    return orders


def build_shipments(df: pd.DataFrame) -> pd.DataFrame:
    """One row per order line with scheduled vs actual shipping days."""
    shipments = df[
        ["Order Item Id", "shipped_ts", "Shipping Mode",
         "Days for shipment (scheduled)", "Days for shipping (real)",
         "Delivery Status", "Late_delivery_risk"]
    ].copy()
    shipments.columns = [
        "order_item_id", "shipped_ts", "shipping_mode", "days_scheduled",
        "days_real", "delivery_status", "late_delivery_risk",
    ]
    return shipments


def load_table(engine: Engine, table: str, data: pd.DataFrame) -> None:
    """Append rows to a table in chunks and log how long it took."""
    start = time.perf_counter()
    data.to_sql(table, engine, if_exists="append", index=False, chunksize=5000, method="multi")
    log.info("Loaded %d rows into %s in %.1fs", len(data), table, time.perf_counter() - start)


def main() -> None:
    """Empty the three tables, then load them again (safe to re-run)."""
    engine = create_engine(config.database_url())
    df = read_raw_csv()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE shipments, orders, products CASCADE"))
    load_table(engine, "products", build_products(df))
    load_table(engine, "orders", build_orders(df))
    load_table(engine, "shipments", build_shipments(df))
    log.info("Done.")


if __name__ == "__main__":
    main()