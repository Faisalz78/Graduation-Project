import re
import uuid
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.invoice_data import InputModel

UserRole = Literal["EMPLOYEE", "PROJECT_MANAGER", "FINANCE_MANAGER"]


def validate_password(value: str) -> str:
    if (
        len(value) < 12
        or not re.search(r"[a-z]", value)
        or not re.search(r"[A-Z]", value)
        or not re.search(r"\d", value)
        or not re.search(r"[^A-Za-z0-9]", value)
    ):
        raise ValueError("كلمة المرور يجب أن تكون 12 خانة وتضم حرفًا كبيرًا وصغيرًا ورقمًا ورمزًا.")
    return value


class UserCreateInput(InputModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    role: UserRole
    temporary_password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("أدخل بريدًا إلكترونيًا صحيحًا.")
        return value

    @field_validator("temporary_password")
    @classmethod
    def strong_password(cls, value):
        return validate_password(value)


class UserUpdateInput(InputModel):
    revision: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=120)
    role: UserRole
    is_active: bool


class PasswordResetInput(InputModel):
    revision: int = Field(gt=0)
    temporary_password: str = Field(min_length=12, max_length=128)

    @field_validator("temporary_password")
    @classmethod
    def strong_password(cls, value):
        return validate_password(value)


class ProjectCreateInput(InputModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=40)

    @field_validator("code")
    @classmethod
    def valid_code(cls, value):
        value = value.upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,39}", value):
            raise ValueError("استخدم أحرفًا إنجليزية وأرقامًا وشرطة فقط في رمز المشروع.")
        return value


class ProjectUpdateInput(ProjectCreateInput):
    revision: int = Field(gt=0)
    is_active: bool


class ProjectMembersInput(InputModel):
    revision: int = Field(gt=0)
    members: list[uuid.UUID] = Field(max_length=500)

    @field_validator("members")
    @classmethod
    def unique_members(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("قائمة أعضاء المشروع تحتوي حسابًا مكررًا.")
        return value
