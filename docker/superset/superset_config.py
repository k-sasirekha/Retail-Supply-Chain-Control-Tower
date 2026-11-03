"""Superset settings. Secrets come from environment variables (the .env file), never from code."""
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    "@postgres:5432/superset"
)

# Needed for the what-if panel: lets a dashboard filter change the SQL (Jinja templating)
FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": True}