from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.db import Base


class FormModuleAnswer(Base):
    __tablename__ = "form_module_answers"
    __table_args__ = (
        UniqueConstraint("form_id", "question_id", name="uq_form_module_answers_form_question"),
    )

    id = Column(Integer, primary_key=True, index=True)
    form_id = Column(Integer, ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("form_questions.id", ondelete="CASCADE"), nullable=False, index=True)

    reference = Column(String(255), nullable=False)
    output_json = Column(Text, nullable=True)
    output_summary_text = Column(Text, nullable=True)
    output_summary_html = Column(Text, nullable=True)
    output_bom_json = Column(Text, nullable=True)
    output_docx_path = Column(String(500), nullable=True)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
