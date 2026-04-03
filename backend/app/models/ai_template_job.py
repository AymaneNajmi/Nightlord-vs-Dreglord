import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.db import Base
from app.models.techno import DocType


class AITemplateJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class AITemplateJob(Base):
    __tablename__ = "ai_template_jobs"

    id = Column(Integer, primary_key=True, index=True)
    techno_name = Column(String(255), nullable=False)
    template_type = Column(String(120), nullable=True)
    doc_type = Column(Enum(DocType), nullable=False, default=DocType.INGENIERIE)
    cover_template_id = Column(Integer, ForeignKey("template_docs.id", ondelete="SET NULL"), nullable=True)
    llm_provider = Column(String(20), nullable=False, default="openai")

    status = Column(Enum(AITemplateJobStatus), nullable=False, default=AITemplateJobStatus.PENDING)
    progress = Column(Integer, nullable=False, default=0)
    logs = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    redaction_report = Column(JSON, nullable=True)
    source_files = Column(JSON, nullable=True)
    output_payload = Column(JSON, nullable=True)

    template_doc_id = Column(Integer, ForeignKey("template_docs.id", ondelete="SET NULL"), nullable=True)
    form_template_id = Column(Integer, ForeignKey("form_templates.id", ondelete="SET NULL"), nullable=True)
    techno_id = Column(Integer, ForeignKey("technos.id", ondelete="SET NULL"), nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    techno = relationship("Techno", foreign_keys=[techno_id])
    template_doc = relationship("TemplateDoc", foreign_keys=[template_doc_id])
    form_template = relationship("FormTemplate", foreign_keys=[form_template_id])
    cover_template = relationship("TemplateDoc", foreign_keys=[cover_template_id])
