import enum

from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.db import Base
from app.models.user_techno import user_technos

class DocType(str, enum.Enum):
    INGENIERIE = "INGENIERIE"
    EXPLOITATION = "EXPLOITATION"

class Techno(Base):
    __tablename__ = "technos"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    doc_type = Column(Enum(DocType), nullable=False, default=DocType.INGENIERIE)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    template_doc_id = Column(Integer, ForeignKey("template_docs.id", ondelete="SET NULL"), nullable=True)
    form_template_id = Column(Integer, ForeignKey("form_templates.id", ondelete="SET NULL"), nullable=True)
    cover_template_id = Column(Integer, ForeignKey("template_docs.id", ondelete="SET NULL"), nullable=True)

    creator = relationship("User", foreign_keys=[created_by])
    template_doc = relationship("TemplateDoc", foreign_keys=[template_doc_id])
    form_template = relationship("FormTemplate", foreign_keys=[form_template_id])
    cover_template = relationship("TemplateDoc", foreign_keys=[cover_template_id])
    assigned_users = relationship(
        "User",
        secondary=user_technos,
        back_populates="assigned_technos",
        lazy="selectin",
    )

    documents = relationship(
        "TemplateDoc",
        back_populates="techno",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="TemplateDoc.techno_id",
    )

    # ✅ NEW
    forms = relationship(
        "FormTemplate",
        back_populates="techno",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="FormTemplate.techno_id",
    )
