from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import SessionLocal
from app.models.techno import Techno
from app.models.user import Role, User
from app.services.access_control import visible_technos_query

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"], dependencies=[Depends(require_admin)])


class UserCreate(BaseModel):
    email: str
    full_name: Optional[str] = None
    password: str = Field(min_length=1)
    role: Role = Role.USER
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class TechnoAssignments(BaseModel):
    techno_ids: List[int] = []


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": str(u.role).split(".")[-1],
            "is_active": u.is_active,
            "assigned_technos": [{"id": t.id, "name": t.name} for t in u.assigned_technos],
        }
        for u in users
    ]


@router.post("")
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")
    exists = db.query(User).filter(User.email == email).first()
    if exists:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        email=email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"ok": True, "id": user.id}


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password:
        user.password = payload.password
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return {"ok": True, "id": user.id}


@router.delete("/{user_id}")
def deactivate_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    return {"ok": True, "id": user.id, "is_active": user.is_active}


@router.get("/{user_id}/technos")
def list_user_technos(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return [{"id": t.id, "name": t.name} for t in user.assigned_technos]


@router.put("/{user_id}/technos")
def set_user_technos(
    user_id: int,
    payload: TechnoAssignments,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    requested_ids = set(payload.techno_ids or [])
    if not requested_ids:
        user.assigned_technos = []
        db.commit()
        return {"ok": True, "assigned_ids": []}

    allowed_technos = (
        visible_technos_query(db, current_admin)
        .filter(Techno.id.in_(requested_ids))
        .all()
    )
    allowed_ids = {t.id for t in allowed_technos}
    if allowed_ids != requested_ids:
        raise HTTPException(status_code=403, detail="Forbidden")

    user.assigned_technos = allowed_technos
    db.commit()
    return {"ok": True, "assigned_ids": sorted(allowed_ids)}
