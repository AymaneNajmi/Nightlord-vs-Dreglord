from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey

from app.core.db import Base


class Worksheet(Base):
    __tablename__ = "worksheets"

    id = Column(Integer, primary_key=True, index=True)

    # optionnel: lier un worksheet à une techno
    techno_id = Column(Integer, ForeignKey("technos.id"), nullable=True)

    filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    mime_type = Column(String(120), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
