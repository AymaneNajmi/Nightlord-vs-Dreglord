from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.db import Base

class TemplateDoc(Base):
    __tablename__ = "template_docs"

    id = Column(Integer, primary_key=True, index=True)
    techno_id = Column(Integer, ForeignKey("technos.id", ondelete="CASCADE"), nullable=False)

    filename = Column(String(255), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    mime_type = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_generated = Column(Boolean, nullable=False, default=False)
    outline_json = Column(JSON, nullable=True)
    template_text = Column(Text, nullable=True)

    # ✅ doit matcher Techno.documents
    techno = relationship("Techno", back_populates="documents", foreign_keys=[techno_id])
    
