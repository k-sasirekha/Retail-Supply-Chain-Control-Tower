# Retail and Supply Chain Control Tower

A near real-time view of inventory, deliveries and suppliers that warns about problems before they hurt sales. Built as an internship project: PostgreSQL, Airflow, Prophet, anomaly detection, Superset and Slack/email alerts, all running locally in Docker.

## What it does

- Loads real order and shipment data (DataCo Smart Supply Chain, CC0) and simulates suppliers, deliveries and inventory on top of it.
- Refreshes every hour with an Airflow DAG that replays history one day per run.
- Calculates four KPIs as SQL views: stock-out rate, on-time delivery, supplier lead time, days of inventory.
- Detects demand spikes and supplier delays with a z-score baseline and an Isolation Forest, and scores them against labeled anomalies.
- Forecasts demand with Prophet and compares it with current stock and incoming deliveries.
- Shows three Superset dashboards, including a what-if panel (supplier delayed by 0, 3, 5, 7, 10 or 14 days).
- Sends deduplicated alerts to Slack and email, with thresholds stored in a database table.

See [docs/architecture.md](docs/architecture.md) for the diagram, [docs/data_dictionary.md](docs/data_dictionary.md) for every table and view, and [docs/results.md](docs/results.md) for every measured number.

## Headline results

| Area | Result |
|---|---|
| Forecast accuracy (14 products, 92-day backtest) | Prophet RMSE 8.83 vs 12.21 for the naive baseline; better on 9 of 14 products |
| Supplier-delay detection | 9 of 10 labeled delays caught (90% recall); best F1 64.8% (Isolation Forest) |
| Demand-spike detection | Weak: best recall 54.5% (z-score); best F1 14.0% (Isolation Forest) |
| Index effect on a three-month product query | Roughly 14 to 20 times faster with the indexes (measured three times) |
| Tests | 19 unit tests |

Precision for supplier delays is understated: unreliable suppliers are late at random by design, and those real late deliveries count as false positives because only injected delays are labeled.

## Quick start

Needs Docker Desktop (at least 6 GB of memory for Docker), Git, Python 3.11 and PowerShell. Tested on Windows.

1. Clone the repository and open the folder.

```powershell
git clone https://github.com/k-sasirekha/Retail-Supply-Chain-Control-Tower.git
cd Retail-Supply-Chain-Control-Tower
```

2. Create a virtual environment and install the packages.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Create your settings file and edit the values (passwords, `SUPERSET_SECRET_KEY`). `.env` is never committed.

```powershell
Copy-Item .env.example .env
```

4. Download `DataCoSupplyChainDataset.csv` from Kaggle (dataset "DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS" by Shashwat Tiwari) and create the folder first with `mkdir data\raw`, then save it as `data\raw\DataCoSupplyChainDataset.csv`. The file is about 96 MB and is not in the repository.

5. Start Postgres and create the two extra databases that Airflow and Superset need (use your `POSTGRES_USER` from `.env`).

```powershell
docker compose up -d postgres
docker exec ct_postgres psql -U ct_admin -d warehouse -c "CREATE DATABASE airflow;"
docker exec ct_postgres psql -U ct_admin -d warehouse -c "CREATE DATABASE superset;"
```

6. Create the tables, indexes, views and alert rules.

```powershell
.\scripts\apply_sql.ps1
```

7. Start everything else. The first build downloads 1 to 2 GB and takes 5 to 10 minutes.

```powershell
docker compose up -d --build
```

| Service | Address | Login |
|---|---|---|
| Airflow | http://localhost:8080 | `admin` and `AIRFLOW_ADMIN_PASSWORD` |
| Superset | http://localhost:8088 | `admin` and `SUPERSET_ADMIN_PASSWORD` |
| MailHog (alert emails) | http://localhost:8025 | none |

## Build the data

Run these in order from the project folder (the order matters: some scripts clear tables that later ones fill).

```powershell
$env:PYTHONPATH = "src"
python -m control_tower.ingest.load_dataco
python -m control_tower.simulate.make_suppliers
python -m control_tower.simulate.inject_demand_spikes
python -m control_tower.simulate.make_supplier_delays
python -m control_tower.simulate.simulate_inventory
python -m control_tower.detect.run_detectors
python -m control_tower.detect.run_detector_v2
python -m control_tower.detect.score_detectors
python -m control_tower.forecast.backtest
python -m control_tower.forecast.score_forecast
python -m control_tower.forecast.stock_vs_forecast
python -m control_tower.forecast.daily_paths
```

`run_detectors` clears all detections, so always run `run_detector_v2` after it. A fresh setup starts the replay clock at 2017-01-01, so your numbers will differ slightly from `docs/results.md`, which was measured with the clock at 2017-01-13.

## Run the hourly pipeline

The DAG `hourly_refresh` starts paused. Each run moves the replay clock forward one day, checks the alert rules and sends new alerts.

```powershell
docker exec ct_airflow airflow dags unpause hourly_refresh
docker exec ct_airflow airflow dags pause hourly_refresh
```

To run the whole DAG once without waiting: `docker exec ct_airflow airflow dags test hourly_refresh 2026-11-05`

## Dashboards

`superset/dashboards_export.zip` holds three dashboards (KPIs, Forecasts, What-If), their nine charts and the datasets. **The import has not been tested from a clean install.** The command to try is:

```powershell
docker cp superset\dashboards_export.zip ct_superset:/tmp/dashboards_export.zip
docker exec ct_superset superset import-dashboards -p /tmp/dashboards_export.zip -u admin
```

The export masks the database password, so after importing, open Settings, then Database Connections, edit `Control Tower Warehouse` and enter the `POSTGRES_PASSWORD` from your `.env`. The connection URI is `postgresql+psycopg2://<user>:<password>@postgres:5432/warehouse` (the host is `postgres`, not `localhost`, because Superset runs inside Docker).

## Alerts

Four rules live in the `alert_config` table. To change a threshold, edit the row and no code changes:

```powershell
docker exec ct_postgres psql -U ct_admin -d warehouse -c "UPDATE alert_config SET threshold = 25 WHERE rule_name = 'stockout_rate_high';"
```

Slack is optional: create an incoming webhook at https://api.slack.com/apps and put the URL in `SLACK_WEBHOOK_URL` in `.env`. Without it, alerts stay `pending` and email still works through MailHog.

## Tests and benchmarks

```powershell
python -m pytest -q
python -m control_tower.benchmarks.run_benchmarks
```

The second command rewrites `docs/results.md` with live query timings.

## Project layout

```
dags/                  Airflow DAG (hourly_refresh)
docker/                Dockerfiles for Airflow and Superset
docs/                  architecture, results, score tables
scripts/               apply_sql.ps1 (applies every SQL file in order)
sql/schema/            tables and indexes
sql/seeds/             alert thresholds
sql/views/             KPI, forecast and what-if views
src/control_tower/     ingest, simulate, pipeline, detect, forecast, alerts, benchmarks
superset/              exported dashboards
tests/                 unit tests
```

## Design decisions

- **Replay clock:** the dataset is historical, so each hourly run releases one more day of it. This makes incremental loads and "near real-time" demonstrable.
- **Labeled anomalies:** real data has no labels, so known demand spikes and supplier delays are injected into a copy of the data. The detectors never read the labels, which are used only for scoring.
- **Plain views, not materialized views:** the KPI views depend on the replay clock, which moves every hour, so cached results would be stale. The slowest view (what-if, under 1.3 s) is the best candidate if caching were ever needed.
- **What-if panel with precomputed delays:** the view holds six scenarios and a dashboard filter picks one. This is simpler and more reliable than injecting values into SQL with templates, but the delay can only be one of the six preset values.
- **Alert deduplication:** a rule and entity cannot alert again inside its cooldown (6 hours by default), measured in real time.

## Known limitations

- Inventory, suppliers and deliveries are simulated. Orders and shipments are real.
- Only 14 products qualified for the forecast backtest: most of the 118 products stopped selling before the end of the data.
- Demand-spike detection is weak. A more robust baseline (median and MAD) made it worse, and the result is kept as a documented negative result.
- The hourly DAG does not re-run the forecast, so the Forecasts and What-If dashboards stay as of the last manual run.
- MailHog is a local test mailbox. Real email would need SMTP settings and credentials.
- The Airflow image installs its Python packages without pinned versions, so a rebuild months from now could pick up newer releases than the ones measured here (`requirements.txt` pins the versions used on the development machine).
- Not tested from a clean install: the whole Quick start run, and the Superset dashboard import.