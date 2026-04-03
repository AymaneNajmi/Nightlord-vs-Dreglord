import enum

from sqlalchemy import Boolean, Column, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.user_techno import user_technos


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password = Column(String, nullable=False)  # plain text for now (POC)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.USER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    assigned_technos = relationship(
        "Techno",
        secondary=user_technos,
        back_populates="assigned_users",
        lazy="selectin",
    )
