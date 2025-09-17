# app/schemas/auth.py

from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserProfile(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None