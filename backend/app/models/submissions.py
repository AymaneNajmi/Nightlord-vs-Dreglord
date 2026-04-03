from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.db import Base

class FormSubmission(Base):
    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    form_id = Column(Integer, ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False)

    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ✅ NEW: contenu rich html pour [[INSERER]]
    insert_html = Column(Text, nullable=True)

    answers = relationship("SubmissionAnswer", back_populates="submission", cascade="all, delete-orphan")

class SubmissionAnswer(Base):
    __tablename__ = "submission_answers"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=False)

    question_id = Column(Integer, ForeignKey("form_questions.id", ondelete="CASCADE"), nullable=False)

    # on stocke tout en texte (single ou multi -> "A;B;C")
    value_text = Column(Text, nullable=True)
    other_text = Column(Text, nullable=True)

    submission = relationship("FormSubmission", back_populates="answers")
