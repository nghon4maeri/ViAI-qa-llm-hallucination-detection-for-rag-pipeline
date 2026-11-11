# backend/app/core/database.py
import re
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from backend.app.core.config import settings
from backend.app.core.logging import logger

connect_args = {}
engine_kwargs = {
    "echo": settings.DB_ECHO,
}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif settings.DATABASE_URL.startswith("postgresql"):
    engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def ensure_database_exists():
    """
    Safely verifies whether target database exists on PostgreSQL and creates it if missing.
    Prevents startup failures when postgres_data volume was initialized prior to ViAI-QA.
    """
    db_url = settings.DATABASE_URL
    if not db_url.startswith("postgresql"):
        return

    # Extract target database name
    match = re.search(r"/([^/?]+)(\?.*)?$", db_url)
    if not match:
        return
    target_db = match.group(1)

    # Base admin connection URL (connecting to 'postgres' or 'mlflow' maintenance db)
    admin_url = db_url.rsplit("/", 1)[0] + "/postgres"
    try:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": target_db}
            ).fetchone()
            if not result:
                logger.info(f"Target database '{target_db}' missing. Creating...")
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                logger.info(f"Database '{target_db}' created successfully.")
            else:
                logger.info(f"Database '{target_db}' verified.")
        admin_engine.dispose()
    except Exception as exc:
        # Fallback: if 'postgres' DB isn't available, try connecting to current db directly
        logger.warning(f"Auto-database check could not connect to admin db ({exc}). Proceeding with standard pool.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for scoped database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
