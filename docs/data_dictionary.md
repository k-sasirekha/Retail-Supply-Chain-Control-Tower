# Data dictionary

Generated on 2026-11-05 by `python -m control_tower.docgen.make_data_dictionary` from the live database. Do not edit by hand: change the descriptions in the script and run it again.

Source: **real** = from the DataCo CSV, **simulated** = created by the scripts in `simulate/`, **derived** = calculated by the pipeline, **config** = settings.

15 tables and 7 views. Row counts are from the generation date.

## Tables

### `products`

One row per product (118). Names, categories and prices are real; supplier_id is assigned at random by make_suppliers.

Source: real + simulated. Rows: 118.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | no | PK |  |
| product_name | text | no |  |  |
| category_id | integer | yes |  |  |
| category_name | text | yes |  |  |
| department_name | text | yes |  |  |
| unit_price | numeric(10,2) | yes |  |  |
| supplier_id | integer | yes | FK to suppliers.supplier_id |  |

### `suppliers`

Eight fictional suppliers with different reliability and lead times.

Source: simulated. Rows: 8.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| supplier_id | integer | no | PK |  |
| supplier_name | text | no |  |  |
| country | text | yes |  |  |
| reliability_score | numeric(4,3) | no |  | 0 to 1. Chance that a delivery arrives without a random extra delay. |
| base_lead_time_days | integer | no |  | Typical days from restock order to arrival. |
| lead_time_stddev | numeric(5,2) | no |  | Spread (standard deviation) of the lead time in days. |

### `orders`

One row per order line. Rows with order_item_id of 100,000,000 or more are injected copies that create demand spikes; all other rows are real DataCo orders.

Source: real + simulated. Rows: 182,988.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| order_item_id | bigint | no | PK | Unique id of the order line. 100,000,000 or more means an injected spike copy. |
| order_id | bigint | no |  |  |
| order_ts | timestamp | no |  |  |
| product_id | integer | no | FK to products.product_id |  |
| market | text | yes |  | DataCo sales market. |
| order_region | text | yes |  |  |
| order_country | text | yes |  |  |
| quantity | integer | no |  |  |
| unit_price | numeric(10,2) | yes |  |  |
| discount | numeric(10,2) | yes |  |  |
| sales | numeric(12,2) | yes |  |  |
| order_status | text | yes |  |  |
| loaded_at | timestamptz | no |  | When the row was loaded into Postgres. |

### `shipments`

One row per real order line: scheduled versus actual shipping days.

Source: real. Rows: 180,519.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| order_item_id | bigint | no | PK, FK to orders.order_item_id |  |
| shipped_ts | timestamp | yes |  | Shipping date from DataCo. |
| shipping_mode | text | yes |  |  |
| days_scheduled | integer | yes |  | Days the shipment was scheduled to take. |
| days_real | integer | yes |  | Days it actually took. |
| delivery_status | text | yes |  |  |
| late_delivery_risk | smallint | yes |  | DataCo's own late-delivery flag, copied as is. |
| is_late | boolean | yes |  | Generated column: true when days_real is greater than days_scheduled. The on-time KPI uses it. |

### `supplier_deliveries`

Restock orders placed by the inventory simulation, with expected and actual arrival.

Source: simulated. Rows: 4,344.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| delivery_id | bigint | no | PK |  |
| supplier_id | integer | no | FK to suppliers.supplier_id |  |
| product_id | integer | no | FK to products.product_id |  |
| ordered_ts | timestamp | no |  |  |
| expected_ts | timestamp | no |  | ordered_ts plus the supplier's base lead time. |
| received_ts | timestamp | yes |  | Actual arrival. Empty if it arrives after the end of the data. |
| quantity | integer | no |  |  |

### `inventory_snapshots`

Daily stock level per product, produced by replaying demand against a reorder rule.

Source: simulated. Rows: 73,393.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| snapshot_ts | timestamp | no | PK |  |
| product_id | integer | no | PK, FK to products.product_id |  |
| market | text | no | PK | Always ALL: one network-wide stock per product. |
| on_hand | integer | no |  | Units in stock at the end of the day. |
| on_order | integer | no |  | Units ordered from the supplier and not yet arrived. |
| reorder_point | integer | no |  | Stock level (on hand plus on order) at which a restock order is placed. |

### `anomaly_labels`

The answer key: injected demand spikes and supplier delays. The detectors never read this table; it is used only to score them.

Source: simulated. Rows: 21.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| label_id | integer | no | PK |  |
| anomaly_type | text | no |  |  |
| entity_type | text | no |  |  |
| entity_id | integer | no |  | product_id for demand spikes, supplier_id for supplier delays (see entity_type). |
| start_ts | timestamp | no |  | Start of the anomaly window. |
| end_ts | timestamp | no |  | End of the window (exclusive). |
| magnitude | numeric(8,2) | yes |  | Demand spike: the multiplier (3 to 5). Supplier delay: extra days late. |

### `detected_anomalies`

Everything the detectors flagged.

Source: derived. Rows: 1,085.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| detection_id | bigint | no | PK |  |
| detector | text | no |  | zscore, isolation_forest or robust_zscore. |
| anomaly_type | text | no |  |  |
| entity_type | text | no |  |  |
| entity_id | integer | no |  | product_id or supplier_id, depending on entity_type. |
| event_ts | timestamp | no |  | Day of the flagged demand, or the order day of the flagged delivery. |
| score | numeric(10,3) | yes |  | The detector's own score. Scales differ between detectors. |
| detected_at | timestamptz | no |  | When the detector run saved this row. |

### `demand_forecasts`

Prophet backtest results next to the naive baseline and real sales, for the products and test days used in the accuracy measurement.

Source: derived. Rows: 1,288.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | no | PK, FK to products.product_id |  |
| day | date | no | PK |  |
| yhat | numeric(10,2) | no |  | Prophet's expected units for the day. |
| yhat_lower | numeric(10,2) | no |  | Lower end of Prophet's prediction interval. |
| yhat_upper | numeric(10,2) | no |  | Upper end of Prophet's prediction interval. |
| naive | numeric(10,2) | no |  | Naive baseline: the last training week repeated. |
| actual_real | numeric(10,2) | no |  | Units really sold (injected spike copies excluded). Used for scoring. |
| actual_total | numeric(10,2) | no |  | Units sold including injected spike copies. |

### `stock_risk`

Current stock-out risk per product at the replay clock: forecast demand against stock and incoming deliveries.

Source: derived. Rows: 30.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | no | PK, FK to products.product_id |  |
| as_of_ts | timestamp | no |  | Replay clock when the row was calculated. |
| on_hand | integer | no |  |  |
| on_order | integer | no |  |  |
| incoming_14d | integer | no |  | Units from deliveries arriving in the next 14 days. |
| forecast_14d | numeric(10,1) | no |  | Prophet's expected demand over the next 14 days. |
| forecast_14d_high | numeric(10,1) | no |  | The same, using Prophet's upper bound. |
| days_of_cover | numeric(8,1) | yes |  | on_hand divided by the average expected daily demand. |
| stockout_day_expected | smallint | yes |  | First day (1 = replay-clock day) stock reaches zero with expected demand. Empty if not within 14 days. |
| stockout_day_high | smallint | yes |  | The same with the high-demand forecast. |
| risk_level | text | no |  | high if the expected stock-out is within 7 days; medium if later or only at high demand; low if neither. |
| created_at | timestamptz | no |  |  |

### `stock_forecast_daily`

Prophet's expected demand for each of the next 14 days per product; input to the what-if view.

Source: derived. Rows: 420.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | no | PK, FK to products.product_id |  |
| day_no | smallint | no | PK | Day 1 is the replay-clock day, up to day 14. |
| expected | numeric(10,3) | no |  |  |
| expected_high | numeric(10,3) | no |  |  |

### `replay_state`

Single row holding the replay clock.

Source: config. Rows: 1.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| id | integer | no | PK | Always 1: this is a single-row table. |
| watermark_ts | timestamp | no |  | The replay clock. Every KPI view and the alert engine only see data before it. |
| slice_hours | integer | no |  | How far the clock moves in each run. |
| updated_at | timestamptz | no |  |  |

### `pipeline_runs`

One row per hourly refresh run.

Source: derived. Rows: 12.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| run_id | bigint | no | PK |  |
| started_at | timestamptz | no |  | Real time the run started. |
| finished_at | timestamptz | yes |  | Real time the run finished. |
| from_ts | timestamp | no |  | Start of the slice of data covered by the run. |
| to_ts | timestamp | no |  | End of that slice (the new clock position). |
| orders_seen | integer | yes |  | Order lines inside the slice. |
| status | text | no |  |  |

### `alert_config`

Alert rules and thresholds. Edit a row to change an alert, with no code change.

Source: config. Rows: 4.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| rule_name | text | no | PK |  |
| description | text | no |  |  |
| comparison | text | no |  | gt = alert when the metric is above the threshold; lt = alert when below. |
| threshold | numeric(10,2) | no |  |  |
| min_volume | numeric(10,2) | yes |  | Minimum daily demand for the product rule. Empty for other rules. |
| severity | text | no |  | warning or critical. |
| cooldown_hours | integer | no |  | Hours before the same rule and entity can alert again. |
| enabled | boolean | no |  |  |
| updated_at | timestamptz | no |  |  |

### `alert_log`

Every alert that was raised, with Slack and email delivery status. Also used to avoid sending the same alert twice.

Source: derived. Rows: 3.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| alert_id | bigint | no | PK |  |
| rule_name | text | no | FK to alert_config.rule_name |  |
| entity_key | text | no |  | What the alert is about: global, supplier:ID or product:ID. |
| severity | text | no |  |  |
| message | text | no |  |  |
| metric_value | numeric(12,2) | no |  |  |
| threshold | numeric(10,2) | no |  |  |
| data_ts | timestamp | no |  | Date of the data that crossed the threshold. |
| fired_at | timestamptz | no |  | Real time the alert was recorded. The cooldown uses it. |
| slack_status | text | no |  | pending, sent or failed. |
| email_status | text | no |  | pending, sent or failed. |

## Views

### `v_kpi_stockout_daily`

KPI 1. Per day: products tracked, products at zero stock, stock-out rate. Only days before the replay clock.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| day | date | yes |  |  |
| products_tracked | bigint | yes |  |  |
| products_out_of_stock | bigint | yes |  |  |
| stockout_rate_pct | numeric | yes |  | Share of tracked products with zero stock that day, in percent. |

### `v_kpi_ontime_daily`

KPI 2. Per day and shipping mode: shipments, on-time shipments, on-time rate.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| day | date | yes |  |  |
| shipping_mode | text | yes |  |  |
| shipments | bigint | yes |  |  |
| on_time | bigint | yes |  |  |
| ontime_rate_pct | numeric | yes |  | Share of shipments not late, in percent. To combine days, divide summed on_time by summed shipments instead of averaging this column. |

### `v_kpi_supplier_leadtime`

KPI 3. Per supplier and month: deliveries, average lead time, average days late. Only deliveries that arrived before the replay clock.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| supplier_id | integer | yes |  |  |
| supplier_name | text | yes |  |  |
| month | date | yes |  |  |
| deliveries | bigint | yes |  |  |
| avg_lead_time_days | numeric | yes |  | Average days from restock order to arrival. |
| avg_days_late | numeric | yes |  | Average days between expected and actual arrival. |

### `v_kpi_days_of_inventory`

KPI 4. Latest stock per product divided by the average daily demand of the last 14 days.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | yes |  |  |
| product_name | text | yes |  |  |
| supplier_name | text | yes |  |  |
| as_of_day | date | yes |  |  |
| on_hand | integer | yes |  |  |
| on_order | integer | yes |  |  |
| reorder_point | integer | yes |  |  |
| daily_demand_14d | numeric | yes |  | Average units sold per day over the 14 days before the replay clock. |
| days_of_inventory | numeric | yes |  | on_hand divided by daily_demand_14d. Empty when there were no sales in the last 14 days. |

### `v_stock_risk`

stock_risk with product and supplier names, for the dashboards.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | yes |  |  |
| product_name | text | yes |  |  |
| supplier_name | text | yes |  |  |
| as_of_day | date | yes |  |  |
| on_hand | integer | yes |  |  |
| incoming_14d | integer | yes |  |  |
| forecast_14d | numeric(10,1) | yes |  |  |
| days_of_cover | numeric(8,1) | yes |  |  |
| stockout_day_expected | smallint | yes |  |  |
| stockout_day_high | smallint | yes |  |  |
| risk_level | text | yes |  |  |

### `v_detector_scores`

Recall and precision of each detector against anomaly_labels.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| detector | text | yes |  |  |
| anomaly_type | text | yes |  |  |
| labels | bigint | yes |  |  |
| caught | bigint | yes |  |  |
| detections | bigint | yes |  |  |
| correct | bigint | yes |  |  |
| recall_pct | numeric | yes |  | Share of labeled anomalies caught. |
| precision_pct | numeric | yes |  | Share of detections inside a labeled window. Understated; see results.md. |

### `v_whatif_stockout`

What-if: stock-out day per product for each supplier delay of 0, 3, 5, 7, 10 or 14 days. A delay of 0 reproduces stock_risk.

| Column | Type | Null | Key | Notes |
| --- | --- | --- | --- | --- |
| product_id | integer | yes |  |  |
| product_name | text | yes |  |  |
| supplier_name | text | yes |  |  |
| delay_days | integer | yes |  | Assumed delay applied to every incoming delivery: 0, 3, 5, 7, 10 or 14. |
| stockout_day | smallint | yes |  | First day (1 = replay-clock day) stock reaches zero. Empty if not within 14 days. |
| baseline_stockout_day | smallint | yes |  | stockout_day with a delay of 0 (equals stock_risk.stockout_day_expected). |
| days_earlier | integer | yes |  | How many days earlier the product runs out than with no delay (no stock-out counts as day 15). |
| whatif_risk | text | yes |  | high if stockout_day is 7 or less, medium if later, low if none. |
