from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import relationship

from app.core.db import Base


class FormTemplate(Base):
    __tablename__ = "form_templates"

    __table_args__ = (
        UniqueConstraint("techno_id", "name", "version", name="uq_form_techno_name_version"),
    )

    id = Column(Integer, primary_key=True, index=True)

    techno_id = Column(Integer, ForeignKey("technos.id", ondelete="CASCADE"), nullable=False)
    doc_id = Column(Integer, ForeignKey("template_docs.id", ondelete="RESTRICT"), nullable=False)

    name = Column(String(255), nullable=False)

    # versioning + activation
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)

    # parent/self reference (versions chain)
    parent_id = Column(Integer, ForeignKey("form_templates.id", ondelete="SET NULL"), nullable=True)

    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # relationships
    techno = relationship("Techno", back_populates="forms", foreign_keys=[techno_id])
    doc = relationship("TemplateDoc")

    parent = relationship(
        "FormTemplate",
        remote_side=[id],
        back_populates="children",
        passive_deletes=True,
    )
    children = relationship(
        "FormTemplate",
        back_populates="parent",
        passive_deletes=True,
    )

    sections = relationship(
        "FormSection",
        back_populates="form",
        cascade="all, delete-orphan",
    )


class FormSection(Base):
    __tablename__ = "form_sections"

    id = Column(Integer, primary_key=True, index=True)
    form_id = Column(Integer, ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False)

    sec_key = Column(String(50), nullable=False)          # ex: SEC_1_1
    heading_level = Column(Integer, nullable=False)       # 1 / 2 / 3 ...
    heading_title = Column(String(500), nullable=False)   # ex: 1.1 Objectif du document
    order_index = Column(Integer, nullable=False, default=0)

    section_intent = Column(Text, nullable=True)
    section_example = Column(Text, nullable=True)
    purpose_text = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="OK")
    error_message = Column(Text, nullable=True)

    form = relationship("FormTemplate", back_populates="sections")
    questions = relationship(
        "FormQuestion",
        back_populates="section",
        cascade="all, delete-orphan",
    )


class FormQuestion(Base):
    __tablename__ = "form_questions"

    id = Column(Integer, primary_key=True, index=True)
    section_id = Column(Integer, ForeignKey("form_sections.id", ondelete="CASCADE"), nullable=False)

    label = Column(String(500), nullable=False)
    qtype = Column(String(30), nullable=False, default="single_choice")
    is_required = Column(Boolean, default=False)
    help_text = Column(Text, nullable=True)
    question_key = Column(String(120), nullable=True)
    show_if_json = Column(JSON, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    placeholder_key = Column(String(64), nullable=True)

    section = relationship("FormSection", back_populates="questions")
    options = relationship(
        "FormOption",
        back_populates="question",
        cascade="all, delete-orphan",
    )


class FormOption(Base):
    __tablename__ = "form_options"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("form_questions.id", ondelete="CASCADE"), nullable=False)

    label = Column(String(500), nullable=False)
    value = Column(String(255), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)

    question = relationship("FormQuestion", back_populates="options")
