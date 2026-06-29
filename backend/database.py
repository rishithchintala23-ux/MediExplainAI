"""
database.py – Database Layer
=============================
## Changes
- NEW FILE for Feature 1 (User Auth & Personal Workspace)
- Provides SQLAlchemy engine, session factory, and init_db()
- Uses SQLite by default via DATABASE_URL env var
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mediai.db")

# connect_args only needed for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency – yields a DB session and ensures it's closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables defined in models.py (called at app startup)."""
    # Import models here so Base knows about them before create_all
    import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
