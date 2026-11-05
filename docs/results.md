# Results

Generated on 2026-11-05 by `python -m control_tower.benchmarks.run_benchmarks`.
Machine: Windows-10-10.0.26200-SP0, Python 3.11.9, Postgres 15 in Docker (about 6 GB for Docker).
Replay clock at measurement time: 2017-01-13 00:00:00.

## Data volumes

| table | rows |
| --- | --- |
| products | 118 |
| suppliers | 8 |
| orders | 182,988 |
| shipments | 180,519 |
| supplier_deliveries | 4,344 |
| inventory_snapshots | 73,393 |
| anomaly_labels | 21 |
| detected_anomalies | 1,085 |
| demand_forecasts | 1,288 |
| stock_risk | 30 |
| alert_log | 3 |

## Query performance (views read by the Superset dashboards)

| view | rows returned | median ms (7 runs) |
| --- | --- | --- |
| v_kpi_stockout_daily | 743 | 16.3 |
| v_kpi_ontime_daily | 2822 | 141.7 |
| v_kpi_supplier_leadtime | 195 | 5.5 |
| v_kpi_days_of_inventory | 54 | 28.9 |
| v_stock_risk | 30 | 1.5 |
| v_detector_scores | 5 | 6.0 |
| v_whatif_stockout | 180 | 710.3 |

## Index effect

Query: units sold of the best-selling product over three months, on the orders table.

- With the indexes `idx_orders_product_ts` and `idx_orders_ts`: 1.4 ms (index scan)
- Without them: 28.7 ms (sequential scan (whole table))

## Pipeline

- Successful hourly runs recorded so far: 12
- Time per run: about 1 to 2 s per task and about 5 to 8 s for the whole DAG (4 tasks), measured in Airflow, depending on machine load.

## Timings from earlier runs (taken from the run logs)

| step | time |
| --- | --- |
| Load 180,519 orders into Postgres | 37.8 s |
| Load 180,519 shipments into Postgres | 19.5 s |
| Simulate 4,344 deliveries and 73,393 daily inventory snapshots | 9.0 s |
| Anomaly detectors v1 (z-score and Isolation Forest, 4 detectors) | 1.7 s |
| Robust z-score demand detector (v2) | 3.5 s |
| Prophet backtest, 14 products, 92 test days | 5.6 s |
| Stock risk (forecast vs stock), 30 products | 11.3 s |
| Full hourly DAG run (4 tasks, in Airflow) | 5 to 8 s |
| Unit tests (19) | 2 to 5 s |

## Anomaly detection against the labeled anomalies

| detector | anomaly_type | labels | caught | detections | correct | recall_pct | precision_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| isolation_forest | demand_spike | 11 | 3 | 32 | 3 | 27.3 | 9.4 |
| robust_zscore | demand_spike | 11 | 5 | 673 | 16 | 45.5 | 2.4 |
| zscore | demand_spike | 11 | 6 | 200 | 11 | 54.5 | 5.5 |
| isolation_forest | supplier_delay | 10 | 9 | 85 | 43 | 90.0 | 50.6 |
| zscore | supplier_delay | 10 | 9 | 95 | 44 | 90.0 | 46.3 |

Notes: precision is understated. Unreliable suppliers are late at random by design, and those real late deliveries count as false positives because only the injected delays are labeled. Demand spikes may be missed on products with little sales history (not checked separately).

## Forecast accuracy (backtest: train to 2017-06-30, test 2017-07-01 to 2017-09-30, 14 products)

| model | rmse | mae | mape_pct | wape_pct |
| --- | --- | --- | --- | --- |
| prophet | 8.83 | 5.3 | 25.64 | 22.55 |
| naive | 12.21 | 7.03 | 35.11 | 29.92 |

Prophet beats the naive baseline (RMSE) on 9 of 14 products.
