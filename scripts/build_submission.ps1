# Build the DA-03 submission folder on this PC, ready to drag into Google Drive.
# Run from the project folder with the virtual environment active and Postgres running.
param([string]$Out = "C:\Projects\Capstone_Submission\DA-03")

$root = Split-Path -Parent $PSScriptRoot
$repoUrl = "https://github.com/k-sasirekha/Retail-Supply-Chain-Control-Tower"
$dirs = "01_Presentation","02_Demo_Video","03_Documentation","04_Test_and_Results","05_Screenshots","06_Code","07_Data_Samples","08_Reflection"
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $Out $d) | Out-Null }

Write-Host "Copying documentation and results"
Copy-Item "$root\README.md", "$root\docs\architecture.md", "$root\docs\data_dictionary.md" -Destination "$Out\03_Documentation" -Force
Copy-Item "$root\docs\results.md", "$root\docs\anomaly_scores.csv", "$root\docs\anomaly_scores_v1.csv", "$root\docs\forecast_scores_overall.csv", "$root\docs\forecast_scores_by_product.csv" -Destination "$Out\04_Test_and_Results" -Force

Push-Location $root
Write-Host "Running unit tests"
python -m pytest -v | Out-File -Encoding utf8 "$Out\04_Test_and_Results\pytest_output.txt"
Write-Host "Archiving the committed source code"
git archive --format=zip -o "$Out\06_Code\control-tower-source.zip" HEAD
Pop-Location

Write-Host "Exporting small data samples"
$samples = [ordered]@{
    "orders_sample_1000_rows.csv" = "SELECT * FROM orders WHERE order_item_id < 100000000 ORDER BY order_item_id LIMIT 1000"
    "suppliers.csv"               = "SELECT * FROM suppliers ORDER BY supplier_id"
    "anomaly_labels.csv"          = "SELECT * FROM anomaly_labels ORDER BY label_id"
    "stock_risk.csv"              = "SELECT * FROM v_stock_risk ORDER BY days_of_cover"
    "alert_config.csv"            = "SELECT * FROM alert_config ORDER BY rule_name"
}
foreach ($name in $samples.Keys) {
    $sql = "COPY ($($samples[$name])) TO STDOUT WITH CSV HEADER"
    docker exec ct_postgres psql -U ct_admin -d warehouse -c $sql | Set-Content -Encoding utf8 "$Out\07_Data_Samples\$name"
}

@"
Full dataset (not included, about 96 MB): DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS
by Shashwat Tiwari on Kaggle, CC0 public domain.
https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis
File used: DataCoSupplyChainDataset.csv

The files in this folder are small samples taken from the project database:
orders_sample_1000_rows.csv  first 1,000 real order lines (no personal data columns were ever loaded)
suppliers.csv                the 8 simulated suppliers
anomaly_labels.csv           the 21 injected anomalies (the answer key used only for scoring)
stock_risk.csv               stock-out risk for 30 products at the replay clock
alert_config.csv             the alert rules and their thresholds
"@ | Set-Content -Encoding utf8 "$Out\07_Data_Samples\DATA_SOURCE.txt"

@"
Retail and Supply Chain Control Tower (DA-03)
Sasirekha K

GitHub repository: $repoUrl

A near real-time view of inventory, deliveries and suppliers that warns about problems before they hurt sales.
Stack: PostgreSQL, Apache Airflow, Python, Prophet, Apache Superset, Slack and email alerts, all in Docker.

Folder guide
01_Presentation      final slides and the speaker notes with the demo script
02_Demo_Video        screen recording of the live demo
03_Documentation     README, architecture, data dictionary
04_Test_and_Results  measured results, detector and forecast score tables, unit test output
05_Screenshots       dashboards, alerts, pipeline
06_Code              zip of the committed source code (the GitHub repository is the main copy)
07_Data_Samples      small data samples and where to get the full dataset
08_Reflection        individual reflection

Headline results (details in 04_Test_and_Results/results.md)
- Forecast: Prophet RMSE 8.83 against 12.21 for the naive baseline, better on 9 of 14 products.
- Supplier-delay detection: 9 of 10 labeled delays caught (90 percent recall).
- Demand-spike detection is weak: best recall 54.5 percent.
- Hourly Airflow pipeline with 4 tasks; alerts are deduplicated (7 alerts on the first run, 0 on the second).
- 19 unit tests.
Limits: inventory and suppliers are simulated; only 14 of 118 products were forecast.
"@ | Set-Content -Encoding utf8 "$Out\00_START_HERE.txt"

Write-Host "Done: $Out"