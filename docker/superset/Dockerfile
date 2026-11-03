FROM apache/superset:4.1.2

# Superset needs a driver to talk to Postgres
USER root
RUN pip install --no-cache-dir psycopg2-binary
USER superset