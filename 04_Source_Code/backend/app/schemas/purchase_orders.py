import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from app.schemas.invoice_data import Currency, InputModel


class PurchaseOrderItemInput(InputModel):
    description: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=40)
    ordered_quantity: Annotated[Decimal, Field(gt=0, le=1_000_000, max_digits=14, decimal_places=4)]
    unit_price: Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=18, decimal_places=4)]
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]

    @field_validator("ordered_quantity", "unit_price", "tax_rate", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,18}(?:\.\d{1,4})?", value):
            raise ValueError("أدخل رقمًا عشريًا موجبًا أو صفرًا دون فاصلة آلاف.")
        return value

    @field_validator("unit")
    @classmethod
    def empty_unit(cls, value):
        return value or None


class PurchaseOrderInput(InputModel):
    project_id: uuid.UUID
    supplier_id: uuid.UUID
    number: str = Field(min_length=1, max_length=100)
    order_date: date
    currency: Currency
    items: list[PurchaseOrderItemInput] = Field(min_length=1, max_length=100)

    @field_validator("order_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("التاريخ مطلوب بصيغة YYYY-MM-DD.")
        return value


class ReceiptItemInput(InputModel):
    purchase_order_item_id: uuid.UUID
    received_quantity: Annotated[
        Decimal, Field(gt=0, le=1_000_000, max_digits=14, decimal_places=4)
    ]

    @field_validator("received_quantity", mode="before")
    @classmethod
    def decimal_text(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,10}(?:\.\d{1,4})?", value):
            raise ValueError("كمية الاستلام مطلوبة كرقم موجب حتى أربع منازل.")
        return value


class ReceiptInput(InputModel):
    number: str = Field(min_length=1, max_length=100)
    received_date: date
    note: str | None = Field(default=None, max_length=1000)
    items: list[ReceiptItemInput] = Field(min_length=1, max_length=100)

    @field_validator("received_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("تاريخ الاستلام مطلوب بصيغة YYYY-MM-DD.")
        return value

    @field_validator("note")
    @classmethod
    def empty_note(cls, value):
        return value or None

    @model_validator(mode="after")
    def unique_items(self):
        identifiers = [item.purchase_order_item_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("لا تكرر بند أمر الشراء داخل محضر الاستلام نفسه.")
        return self
