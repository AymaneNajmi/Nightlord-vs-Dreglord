from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, UniqueConstraint, func
from app.core.db import Base

class SubmissionSectionText(Base):
    __tablename__ = "submission_section_texts"

    id = Column(Integer, primary_key=True, index=True)

    submission_id = Column(Integer, ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    form_id = Column(Integer, ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False, index=True)

    sec_key = Column(Text, nullable=False)          # ex: SEC_1_1
    final_text = Column(Text, nullable=False)       # texte édité/validé
    comment = Column(Text, nullable=True)           # commentaire user (optionnel)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("submission_id", "sec_key", name="uq_submission_sec_key"),
    )
