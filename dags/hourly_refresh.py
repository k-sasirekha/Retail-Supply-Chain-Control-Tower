"""Hourly pipeline: advance the replay clock, check alert rules, then send new alerts.

Project code runs in its own Python environment, so it cannot clash with Airflow's libraries.
"""
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
    description="Advance the replay clock, check alert rules, send new alerts",
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
    check = BashOperator(
        task_id="check_alerts",
        bash_command=f"{PYTHON} -m control_tower.alerts.run_alerts --record",
    )
    slack = BashOperator(
        task_id="send_slack",
        bash_command=f"{PYTHON} -m control_tower.alerts.notify",
    )
    email = BashOperator(
        task_id="send_email",
        bash_command=f"{PYTHON} -m control_tower.alerts.notify_email",
        trigger_rule="all_done",
    )

    refresh >> check >> slack >> email