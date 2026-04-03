from sqlalchemy import Column, Integer, Text, String, ForeignKey, DateTime, UniqueConstraint, func
from app.core.db import Base


class SectionOutput(Base):
    __tablename__ = "section_outputs"

    id = Column(Integer, primary_key=True, index=True)

    section_id = Column(Integer, ForeignKey("form_sections.id", ondelete="CASCADE"), nullable=False)
    submission_id = Column(Integer, ForeignKey("form_submissions.id", ondelete="CASCADE"), nullable=False)

    ai_text = Column(Text, nullable=True)
    user_comment = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="draft")  # draft | validated
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("section_id", "submission_id", name="uq_section_outputs_section_submission"),
    )
