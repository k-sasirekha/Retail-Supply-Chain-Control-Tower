FROM apache/airflow:2.10.5-python3.11

# A separate Python environment for our project code, so it cannot clash with Airflow's own libraries.
RUN python -m venv /home/airflow/ct-venv \
    && /home/airflow/ct-venv/bin/pip install --no-cache-dir \
       pandas numpy sqlalchemy psycopg2-binary python-dotenv