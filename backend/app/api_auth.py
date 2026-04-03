# app/api_auth.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_access_token,
    get_current_user,
    get_session_data,
)
from app.core.config import settings
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = (payload.email or "").strip().lower()
    password = (payload.password or "").strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email/password required")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")

    # TEMP (sans hashing)
    if (user.password or "") != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    role = str(user.role).split(".")[-1]
    is_admin = role == "ADMIN"
    redirect = "/admin" if is_admin else "/user"

    session_token = create_access_token(user)
    payload = {
        "ok": True,
        "access_token": session_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": getattr(user, "full_name", None) or user.email.split("@")[0],
            "role": role,
        },
        "redirect": redirect,
    }
    response = JSONResponse(payload)
    cookie_secure = settings.AUTH_COOKIE_SECURE and request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        max_age=SESSION_MAX_AGE_SECONDS,
        secure=cookie_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_COOKIE_PATH,
    )
    return response


@router.post("/logout")
def logout():
    response = JSONResponse({"ok": True, "redirect": "/login"})
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        domain=settings.AUTH_COOKIE_DOMAIN,
        path=settings.AUTH_COOKIE_PATH,
    )
    return response


@router.get("/redirect")
def redirect_for_role(user: User = Depends(get_current_user)):
    role = str(user.role).split(".")[-1]
    is_admin = role == "ADMIN"

    return {
        "ok": True,
        "redirect": "/admin" if is_admin else "/user",
        "role": role,
    }
