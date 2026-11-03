"""Score the Prophet backtest against the naive baseline.

Reports RMSE, MAE, MAPE (days with sales only) and WAPE, a per-product win rate,
and how often real sales fall inside Prophet's prediction interval.
Scored on real demand only, because that is what Prophet was trained on.
"""
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from control_tower import config


def metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, float]:
    """Error measures for one set of predictions."""
    err = predicted - actual
    has_sales = actual > 0
    mape = (err[has_sales].abs() / actual[has_sales]).mean() * 100 if has_sales.any() else np.nan
    wape = err.abs().sum() / actual.sum() * 100 if actual.sum() > 0 else np.nan
    return {
        "rmse": float(np.sqrt((err**2).mean())),
        "mae": float(err.abs().mean()),
        "mape_pct": float(mape),
        "wape_pct": float(wape),
    }


def load() -> pd.DataFrame:
    """Read the backtest results as numbers."""
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM demand_forecasts"), conn)
    cols = ["yhat", "yhat_lower", "yhat_upper", "naive", "actual_real", "actual_total"]
    df[cols] = df[cols].astype(float)
    return df


def main() -> None:
    """Print overall and per-product scores and save them to docs/."""
    df = load()
    rows = []
    for pid, g in df.groupby("product_id"):
        p = metrics(g["actual_real"], g["yhat"])
        n = metrics(g["actual_real"], g["naive"])
        rows.append(
            {
                "product_id": pid,
                "prophet_rmse": p["rmse"], "naive_rmse": n["rmse"],
                "prophet_wape_pct": p["wape_pct"], "naive_wape_pct": n["wape_pct"],
                "units_sold": g["actual_real"].sum(),
            }
        )
    per_product = pd.DataFrame(rows).round(2)
    wins = int((per_product["prophet_rmse"] < per_product["naive_rmse"]).sum())

    overall = pd.DataFrame(
        {
            "prophet": metrics(df["actual_real"], df["yhat"]),
            "naive": metrics(df["actual_real"], df["naive"]),
        }
    ).T.round(2)
    inside = (df["actual_real"] >= df["yhat_lower"]) & (df["actual_real"] <= df["yhat_upper"])

    print(overall.to_string())
    print(f"\nProphet beats naive (RMSE) on {wins} of {len(per_product)} products")
    print(f"Real sales inside Prophet's range: {100 * inside.mean():.1f}% of days")

    docs = config.PROJECT_ROOT / "docs"
    docs.mkdir(exist_ok=True)
    per_product.to_csv(docs / "forecast_scores_by_product.csv", index=False)
    overall.to_csv(docs / "forecast_scores_overall.csv")
    print(f"\nSaved to {docs}")


if __name__ == "__main__":
    main()