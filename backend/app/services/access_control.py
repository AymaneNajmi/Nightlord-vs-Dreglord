from __future__ import annotations

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from app.models.forms import FormTemplate
from app.models.techno import Techno
from app.models.user import User


def _role_name(user: User) -> str:
    return str(user.role).split(".")[-1]


def is_admin(user: User) -> bool:
    return _role_name(user) == "ADMIN"


def visible_technos_query(db: Session, user: User):
    if is_admin(user):
        return db.query(Techno).filter(
            or_(
                Techno.created_by == user.id,
                Techno.assigned_users.any(User.id == user.id),
            )
        )

    return (
        db.query(Techno)
        .filter(Techno.assigned_users.any(User.id == user.id))
        .filter(
            exists().where(
                (FormTemplate.techno_id == Techno.id) & (FormTemplate.is_active.is_(True))
            )
        )
    )


def user_can_access_techno(db: Session, user: User, techno_id: int) -> bool:
    return (
        visible_technos_query(db, user)
        .filter(Techno.id == techno_id)
        .first()
        is not None
    )
