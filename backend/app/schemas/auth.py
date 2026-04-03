# app/schemas/auth.py
from pydantic import BaseModel
from app.models.user import Role

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    role: Role

    class Config:
        from_attributes = True

class LoginIn(BaseModel):
    email: str
    password: str

class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    redirect: str
