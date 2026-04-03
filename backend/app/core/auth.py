from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.user import User

SESSION_COOKIE_NAME = settings.AUTH_COOKIE_NAME
SESSION_MAX_AGE_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MIN * 60


def _normalize_role(role_value: str | None) -> str:
    if not role_value:
        return ""
    return role_value.split(".")[-1]


def _token_expiration() -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MIN)


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": _normalize_role(str(user.role)),
        "exp": _token_expiration(),
        "iat": datetime.now(tz=timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])


def get_user_from_token(token: str, db: Session) -> User | None:
    try:
        session_data = decode_access_token(token)
    except JWTError:
        return None
    user_id = session_data.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def _get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.cookies.get(SESSION_COOKIE_NAME)


def get_session_data(request: Request) -> Dict[str, Any]:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_current_user(
    session_data: Dict[str, Any] = Depends(get_session_data),
    db: Session = Depends(_get_db),
) -> User:
    user_id = session_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def require_authenticated(user: User = Depends(get_current_user)) -> User:
    return user


def require_role(required_role: str):
    def _dependency(user: User = Depends(get_current_user)) -> User:
        actual_role = _normalize_role(str(user.role))
        required = _normalize_role(required_role)
        if actual_role != required:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dependency


require_admin = require_role("ADMIN")
require_user = require_role("USER")
