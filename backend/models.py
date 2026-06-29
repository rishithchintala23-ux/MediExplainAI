"""
models.py – SQLAlchemy ORM Models
====================================
## Changes
- NEW FILE for Feature 1 (User Auth & Personal Workspace)
- User: id, email, hashed_password, created_at
- ReportHistory: id, user_id (FK), uploaded_at, filename, risk_category,
                 risk_score, ai_summary, results_json
"""

import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at     = Column(DateTime, default=datetime.datetime.utcnow)

    reports        = relationship("ReportHistory", back_populates="owner", cascade="all, delete-orphan")


class ReportHistory(Base):
    __tablename__ = "report_history"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at   = Column(DateTime, default=datetime.datetime.utcnow)
    filename      = Column(String, default="manual_entry")
    risk_category = Column(String)
    risk_score    = Column(Float)
    ai_summary    = Column(Text)
    results_json  = Column(Text)   # JSON string of the full results list

    owner         = relationship("User", back_populates="reports")
