"""Choose labeled supplier-delay windows (the answer key for delay detection).

The simulator in the next step reads these labels and delays deliveries inside them.
"""
import logging

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SEED = 11
N_DELAYS = 10
DURATION_DAYS = 14
EXTRA_DAYS_CHOICES = [5, 7, 10, 14]
START = pd.Timestamp("2015-04-01")
END = pd.Timestamp("2017-12-15")


def main() -> None:
    """Replace any old supplier-delay labels with a fresh set (safe to re-run)."""
    engine = create_engine(config.database_url())
    rng = np.random.default_rng(SEED)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM anomaly_labels WHERE anomaly_type = 'supplier_delay'"))
        supplier_ids = [r[0] for r in conn.execute(text("SELECT supplier_id FROM suppliers ORDER BY supplier_id"))]

    slot_days = (END - START).days // N_DELAYS
    labels: list[dict] = []
    for i in range(N_DELAYS):
        offset = int(rng.integers(0, slot_days - DURATION_DAYS))
        start = START + pd.Timedelta(days=i * slot_days + offset)
        end = start + pd.Timedelta(days=DURATION_DAYS)
        supplier = int(rng.choice(supplier_ids))
        extra = int(rng.choice(EXTRA_DAYS_CHOICES))
        labels.append(
            {
                "anomaly_type": "supplier_delay",
                "entity_type": "supplier",
                "entity_id": supplier,
                "start_ts": start,
                "end_ts": end,
                "magnitude": float(extra),
            }
        )
        log.info("Supplier %d: +%d days late from %s to %s", supplier, extra, start.date(), end.date())

    pd.DataFrame(labels).to_sql("anomaly_labels", engine, if_exists="append", index=False)
    log.info("Created %d supplier-delay labels.", len(labels))


if __name__ == "__main__":
    main()