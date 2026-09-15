import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from app.schemas.invoice_data import Currency, InputModel


class ExpenseCategoryInput(InputModel):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=160)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value):
        return value.upper()


class BudgetLineInput(InputModel):
    id: uuid.UUID | None = None
    expense_category_id: uuid.UUID
    description: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=40)
    planned_quantity: Annotated[
        Decimal | None, Field(default=None, gt=0, le=1_000_000, max_digits=14, decimal_places=4)
    ]
    planned_unit_price: Annotated[
        Decimal | None,
        Field(default=None, ge=0, le=1_000_000_000, max_digits=18, decimal_places=4),
    ]
    allocated_amount: Annotated[Decimal, Field(ge=0, le=10**15, max_digits=22, decimal_places=2)]

    @field_validator("planned_quantity", "planned_unit_price", "allocated_amount", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1,4})?", value):
            raise ValueError("أدخل رقمًا عشريًا موجبًا أو صفرًا كنص دون فاصلة آلاف.")
        return value

    @field_validator("unit")
    @classmethod
    def empty_unit(cls, value):
        return value or None

    @model_validator(mode="after")
    def quantity_and_price(self):
        if (self.planned_quantity is None) != (self.planned_unit_price is None):
            raise ValueError("أدخل الكمية وسعر الوحدة معًا، أو اترك الحقلين فارغين.")
        if self.planned_quantity is not None:
            calculated = (self.planned_quantity * self.planned_unit_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if calculated != self.allocated_amount:
                raise ValueError("مخصص البند يجب أن يساوي الكمية المخططة × سعر الوحدة.")
        return self


class ProjectBudgetInput(InputModel):
    currency: Currency
    revision: int = Field(ge=0)
    total_amount: Annotated[Decimal, Field(ge=0, le=10**15, max_digits=22, decimal_places=2)]
    lines: list[BudgetLineInput] = Field(max_length=100)

    @field_validator("total_amount", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,16}(?:\.\d{1,2})?", value):
            raise ValueError("أدخل مبلغًا موجبًا أو صفرًا كنص حتى منزلتين.")
        return value

    @model_validator(mode="after")
    def validate_lines(self):
        ids = [line.id for line in self.lines if line.id]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يمكن تكرار بند الميزانية نفسه في الطلب.")
        if sum((line.allocated_amount for line in self.lines), Decimal("0")) > self.total_amount:
            raise ValueError("مجموع مخصصات البنود يتجاوز إجمالي ميزانية المشروع.")
        return self
