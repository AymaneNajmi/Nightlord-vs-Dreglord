from sqlalchemy import Column, ForeignKey, Table

from app.core.db import Base


user_technos = Table(
    "user_technos",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("techno_id", ForeignKey("technos.id", ondelete="CASCADE"), primary_key=True),
)
