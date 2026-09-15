from typing import Literal

from pydantic import Field, model_validator

from app.schemas.invoice_data import InputModel

InvoiceStatus = Literal[
    "DRAFT", "PROJECT_REVIEW", "FINANCE_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED"
]


class WorkflowInput(InputModel):
    revision: int = Field(ge=1, strict=True)
    action: Literal["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"]
    comment: str | None = Field(default=None, max_length=2000)
    confirmed: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def confirmations(self):
        self.comment = self.comment or None
        if self.action == "SUBMIT" and not self.confirmed:
            raise ValueError("أكد مراجعة بيانات الفاتورة ومطابقتها للأصل قبل الإرسال.")
        if self.action in ("REJECT", "REQUEST_CHANGES") and not self.comment:
            raise ValueError("اكتب سبب الرفض أو تفاصيل التعديل المطلوب.")
        return self
