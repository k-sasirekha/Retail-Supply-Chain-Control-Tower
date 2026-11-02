"""Hourly refresh DAG. Calls our project code in its own private Python environment."""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PYTHON = "/home/airflow/ct-venv/bin/python"

default_args = {
    "owner": "control-tower",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="hourly_refresh",
    description="Advance the replay clock by one slice and log the run",
    default_args=default_args,
    start_date=datetime(2026, 11, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["control-tower"],
) as dag:
    refresh = BashOperator(
        task_id="refresh_once",
        bash_command=f"{PYTHON} -m control_tower.pipeline.refresh",
    )