import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class RegisterRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    # SecretStr keeps the password out of reprs and logs.
    password: SecretStr = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    # No password policy here: a wrong password of any length is just a failed login.
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
