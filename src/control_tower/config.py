"""Project settings, read from the .env file so no secrets live in code."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

POSTGRES_USER: str = os.getenv("POSTGRES_USER", "ct_admin")
POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB: str = os.getenv("POSTGRES_DB", "warehouse")
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")

RAW_CSV_PATH: Path = PROJECT_ROOT / "data" / "raw" / "DataCoSupplyChainDataset.csv"


def database_url() -> str:
    """Build the SQLAlchemy connection string for the warehouse database."""
    return (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
