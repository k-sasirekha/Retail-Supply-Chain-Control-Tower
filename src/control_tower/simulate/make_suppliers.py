"""Create simulated suppliers and assign every product to one of them."""
import logging

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SEED = 42

# (name, country, reliability 0-1, typical lead time in days, lead time spread in days)
SUPPLIERS = [
    ("Apex Sports Supply", "USA", 0.95, 5, 0.8),
    ("Nordic Gear AB", "Sweden", 0.92, 7, 1.0),
    ("Pacific Trade Co", "China", 0.80, 14, 2.5),
    ("Lotus Exports", "India", 0.78, 12, 2.5),
    ("Andes Imports", "Brazil", 0.70, 10, 3.0),
    ("Sahara Logistics", "Egypt", 0.65, 16, 3.5),
    ("Rhine Wholesale GmbH", "Germany", 0.90, 6, 1.0),
    ("Budget Bulk Ltd", "Vietnam", 0.55, 18, 4.0),
]


def build_suppliers() -> pd.DataFrame:
    """Return the supplier table as a DataFrame."""
    return pd.DataFrame(
        SUPPLIERS,
        columns=[
            "supplier_name", "country", "reliability_score",
            "base_lead_time_days", "lead_time_stddev",
        ],
    )


def main() -> None:
    """Insert suppliers and assign each product to a supplier (safe to re-run)."""
    engine = create_engine(config.database_url())
    rng = np.random.default_rng(SEED)

    with engine.begin() as conn:
        conn.execute(text("UPDATE products SET supplier_id = NULL"))
        conn.execute(text("TRUNCATE supplier_deliveries, inventory_snapshots, anomaly_labels"))
        conn.execute(text("DELETE FROM suppliers"))
        conn.execute(text("ALTER SEQUENCE suppliers_supplier_id_seq RESTART WITH 1"))

    build_suppliers().to_sql("suppliers", engine, if_exists="append", index=False)

    with engine.begin() as conn:
        supplier_ids = [r[0] for r in conn.execute(text("SELECT supplier_id FROM suppliers ORDER BY supplier_id"))]
        product_ids = [r[0] for r in conn.execute(text("SELECT product_id FROM products ORDER BY product_id"))]
        assigned = rng.choice(supplier_ids, size=len(product_ids))
        for pid, sid in zip(product_ids, assigned):
            conn.execute(
                text("UPDATE products SET supplier_id = :sid WHERE product_id = :pid"),
                {"sid": int(sid), "pid": int(pid)},
            )
    log.info("Created %d suppliers and assigned %d products.", len(supplier_ids), len(product_ids))


if __name__ == "__main__":
    main()