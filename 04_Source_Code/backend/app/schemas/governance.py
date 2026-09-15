import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.regions import validate_region_code
from app.schemas.invoice_data import InputModel


class ApprovalLimitInput(InputModel):
    amount: Annotated[Decimal, Field(ge=0, le=10**15, max_digits=22, decimal_places=2)]

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1,2})?", value):
            raise ValueError("أدخل الحد كنص عشري موجب أو صفر حتى منزلتين.")
        return value


class SupplierVerificationInput(InputModel):
    status: Literal["PENDING", "VERIFIED", "REJECTED"]
    note: str | None = Field(default=None, max_length=1000)
    region_code: str | None = Field(default=None, max_length=30)

    @field_validator("region_code")
    @classmethod
    def known_region(cls, value):
        return validate_region_code(value or None)

    @model_validator(mode="after")
    def require_evidence_note(self):
        self.note = self.note or None
        if self.status in ("VERIFIED", "REJECTED") and (not self.note or len(self.note) < 3):
            raise ValueError("اكتب ملاحظة تحقق واضحة من ثلاثة أحرف على الأقل.")
        return self
