"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, LoaderCircle, Send } from "lucide-react";
import {
  api,
  ApiError,
  statusLabels,
  type Invoice,
  type InvoiceStatus,
  type WorkflowAction,
} from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { amount } from "@/components/invoice-financial";

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return (
    <span
      className={`draft-badge invoice-status status-${status.toLowerCase()}`}
      data-testid="invoice-status"
    >
      <span />
      {statusLabels[status]}
    </span>
  );
}

const explanations: Record<InvoiceStatus, string> = {
  DRAFT: "أكمل البيانات وراجع الملف الأصلي، ثم أرسل الفاتورة إلى مدير المشروع.",
  PROJECT_REVIEW: "الفاتورة لدى مدير المشروع. يتوقف تعديل البيانات حتى يطلب المراجع تعديلًا.",
  FINANCE_REVIEW: "وافق مدير المشروع على النسخة المرسلة، والفاتورة بانتظار قرار المالية.",
  CHANGES_REQUESTED:
    "عدّل البيانات أو أضف التوضيح في الملاحظة، ثم أعد الإرسال. تبدأ المراجعة من مدير المشروع مجددًا.",
  APPROVED: "اكتملت موافقة مدير المشروع والمالية. هذا السجل يوثق الاعتماد ولا ينفذ عملية دفع.",
  REJECTED: "أُغلقت هذه الفاتورة بالرفض. يمكنك الاطلاع على السبب والبيانات وسجل الإجراءات.",
};

export function InvoiceWorkflow({
  invoice,
  onChanged,
  onReload,
}: {
  invoice: Invoice;
  onChanged: (invoice: Invoice) => void;
  onReload: () => void;
}) {
  const { csrf_token } = useSession();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [action, setAction] = useState<WorkflowAction | null>(null);
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const actions = invoice.workflow?.allowed_actions || [];
  const missing = invoice.workflow?.missing_fields || [];
  const reason = [...(invoice.events || [])]
    .reverse()
    .find(
      (event) =>
        event.action === (invoice.status === "REJECTED" ? "INVOICE_REJECTED" : "CHANGES_REQUESTED"),
    );
  const titles: Record<WorkflowAction, string> = {
    SUBMIT: invoice.status === "CHANGES_REQUESTED" ? "إعادة الإرسال للمراجعة" : "إرسال للمراجعة",
    APPROVE: invoice.status === "PROJECT_REVIEW" ? "موافقة وإرسال للمالية" : "اعتماد الفاتورة",
    REQUEST_CHANGES: "طلب تعديل",
    REJECT: "رفض الفاتورة",
  };
  const confirmations: Record<WorkflowAction, string> = {
    SUBMIT: "تأكيد الإرسال",
    APPROVE: "تأكيد الموافقة",
    REQUEST_CHANGES: "تأكيد طلب التعديل",
    REJECT: "تأكيد الرفض",
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!action || busy || stale) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Invoice>(`/invoices/${invoice.id}/workflow`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          revision: invoice.revision,
          action,
          comment: comment.trim() || null,
          confirmed,
        }),
      });
      if (active.current) onChanged(result);
    } catch (failure) {
      if (!active.current) return;
      setError((failure as Error).message);
      setStale(failure instanceof ApiError && [403, 409].includes(failure.status));
      setBusy(false);
    }
  }
  return (
    <section className="surface workflow-card" aria-labelledby="workflow-title">
      <div className="workflow-heading">
        <div>
          <span className="eyebrow">مسار المراجعة</span>
          <h2 id="workflow-title">{statusLabels[invoice.status]}</h2>
        </div>
        <InvoiceStatusBadge status={invoice.status} />
      </div>
      <ol className="workflow-steps" aria-label="مراحل المراجعة">
        {[
          ["تأكيد الموظف", invoice.status !== "DRAFT"],
          ["موافقة المشروع", !!invoice.workflow?.project_approved_revision],
          ["اعتماد المالية", invoice.status === "APPROVED"],
        ].map(([label, done]) => (
          <li key={String(label)} className={done ? "complete" : ""}>
            <span aria-hidden="true">{done ? <Check size={14} /> : "·"}</span>
            {String(label)}
            <span className="sr-only">{done ? "مكتملة للنسخة المرسلة" : "غير مكتملة"}</span>
          </li>
        ))}
      </ol>
      <p className="workflow-description">{explanations[invoice.status]}</p>
      {invoice.workflow?.approval_authority && (
        <div
          className={
            invoice.workflow.approval_authority.can_approve
              ? "approval-authority allowed"
              : "approval-authority denied"
          }
        >
          <strong>حد الموافقة</strong>
          <p>{invoice.workflow.approval_authority.reason}</p>
          <span>
            حدك: {amount(invoice.workflow.approval_authority.limit, invoice.currency)} · الإجمالي:{" "}
            {amount(invoice.workflow.approval_authority.invoice_total, invoice.currency)}
          </span>
        </div>
      )}
      {["CHANGES_REQUESTED", "REJECTED"].includes(invoice.status) && reason?.details?.comment && (
        <div className="review-reason">
          <strong>
            {invoice.status === "REJECTED" ? "سبب الرفض" : "التعديل المطلوب"} · {reason.actor_name}
          </strong>
          <p>{reason.details.comment}</p>
        </div>
      )}
      {actions.includes("SUBMIT") && missing.length > 0 && (
        <div className="submission-missing">
          <strong>المتبقي قبل الإرسال</strong>
          <ul>
            {missing.map((field) => (
              <li key={field}>{field}</li>
            ))}
          </ul>
        </div>
      )}
      {!action && (
        <div className="workflow-actions">
          {(["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"] as WorkflowAction[])
            .filter((value) => actions.includes(value))
            .map((value) => (
              <Button
                key={value}
                variant={value === "SUBMIT" || value === "APPROVE" ? "default" : "outline"}
                disabled={value === "SUBMIT" && missing.length > 0}
                onClick={() => setAction(value)}
              >
                {value === "SUBMIT" && <Send size={16} />}
                {titles[value]}
              </Button>
            ))}
        </div>
      )}
      {action && (
        <form className="workflow-form" onSubmit={submit}>
          <h3>{titles[action]}</h3>
          <p>
            سيُسجّل الإجراء على النسخة {invoice.revision} · الإجمالي{" "}
            <bdi>
              {invoice.totals ? amount(invoice.totals.grand_total, invoice.currency) : "غير مكتمل"}
            </bdi>
          </p>
          <fieldset className="plain-fieldset" disabled={busy || stale}>
            <div className="field">
              <label htmlFor="review-comment">
                {["REJECT", "REQUEST_CHANGES"].includes(action)
                  ? "السبب والتفاصيل المطلوبة"
                  : "ملاحظة الإجراء (اختياري)"}
              </label>
              <textarea
                id="review-comment"
                className="form-field"
                rows={3}
                maxLength={2000}
                required={["REJECT", "REQUEST_CHANGES"].includes(action)}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </div>
            {action === "SUBMIT" && (
              <label className="confirmation-check">
                <input
                  type="checkbox"
                  required
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                راجعت بيانات الفاتورة والبنود وطابقتها مع الملف الأصلي.
              </label>
            )}
            <div className="workflow-actions">
              <Button type="submit" disabled={busy || stale || (action === "SUBMIT" && !confirmed)}>
                {busy ? <LoaderCircle size={16} className="animate-spin" /> : null}
                {confirmations[action]}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setAction(null);
                  setComment("");
                  setConfirmed(false);
                  setError("");
                }}
              >
                إلغاء الإجراء
              </Button>
            </div>
          </fieldset>
          {error && (
            <div className="error-box" role="alert">
              <p>{error}</p>
              {stale && (
                <Button type="button" variant="outline" onClick={onReload}>
                  تحميل أحدث نسخة للمراجعة
                </Button>
              )}
            </div>
          )}
        </form>
      )}
    </section>
  );
}
