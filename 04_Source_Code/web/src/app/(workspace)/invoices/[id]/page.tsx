"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Check,
  Download,
  FileCode2,
  FileText,
  FolderKanban,
  LoaderCircle,
  ShieldCheck,
  Pencil,
} from "lucide-react";
import { api, eventLabels, statusLabels, type Invoice } from "@/lib/api";
import { fileSize, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { InvoiceDataView } from "@/components/invoice-financial";
import { InvoiceAuditPanel } from "@/components/invoice-audit";
import { InvoiceStatusBadge, InvoiceWorkflow } from "@/components/invoice-workflow";

export default function InvoiceDetails() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    setInvoice(null);
    setNotice("");
    api<Invoice>(`/invoices/${id}`)
      .then((data) => {
        if (active) setInvoice(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [id, attempt]);
  async function download() {
    if (!invoice) return;
    setDownloadError("");
    try {
      const response = await fetch(invoice.attachment.url, {
        credentials: "include",
        cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "تعذر تحميل الملف.");
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = invoice.attachment.name;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setDownloadError((e as Error).message);
    }
  }
  return (
    <div className="page-container">
      <Link className="back-link" href="/invoices">
        <ArrowRight size={17} />
        العودة إلى الفواتير
      </Link>
      {error ? (
        <div className="surface inline-state">
          <p role="alert">{error}</p>
          <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
            إعادة المحاولة
          </Button>
        </div>
      ) : !invoice || invoice.id !== id ? (
        <div className="inline-state">
          <LoaderCircle size={25} className="animate-spin" />
          جارٍ تحميل الفاتورة…
        </div>
      ) : (
        <>
          {params.get("saved") === "1" && (
            <div className="success-box" role="status">
              <Check size={18} />
              تم حفظ المسودة والملف الأصلي بنجاح.
            </div>
          )}
          <div className="page-heading">
            <div>
              <span className="eyebrow">تفاصيل الفاتورة</span>
              <h1 className="detail-title">{invoice.attachment.name}</h1>
              <p>أُضيفت في {formatDate(invoice.created_at)}</p>
            </div>
            <div className="detail-heading-actions">
              {invoice.workflow?.allowed_actions.includes("EDIT") && (
                <Button asChild>
                  <Link href={`/invoices/${id}/edit`}>
                    <Pencil size={16} />
                    تعديل بيانات الفاتورة
                  </Link>
                </Button>
              )}
              <InvoiceStatusBadge status={invoice.status} />
            </div>
          </div>
          {params.get("updated") === "1" && (
            <div className="success-box" role="status">
              <Check size={18} />
              تم حفظ بيانات الفاتورة بنجاح.
            </div>
          )}
          {notice && (
            <div className="success-box" role="status">
              <Check size={18} />
              {notice}
            </div>
          )}
          <InvoiceWorkflow
            key={`${invoice.id}:${invoice.revision}`}
            invoice={invoice}
            onChanged={(data) => {
              setInvoice(data);
              setNotice("تم تسجيل الإجراء بنجاح.");
            }}
            onReload={() => setAttempt((n) => n + 1)}
          />
          <section className="surface invoice-financial">
            <div className="surface-heading">
              <div>
                <h2>بيانات الفاتورة والبنود</h2>
                <p>بيانات مدخلة يدويًا · النسخة {invoice.revision}</p>
              </div>
            </div>
            <div className="financial-content">
              <InvoiceDataView data={invoice} />
            </div>
          </section>
          {invoice.audit && <InvoiceAuditPanel audit={invoice.audit} currency={invoice.currency} />}
          <div className="detail-layout">
            <section className="surface">
              <div className="surface-heading">
                <div>
                  <h2>الملف الأصلي</h2>
                  <p>
                    {fileSize(invoice.attachment.size_bytes)} ·{" "}
                    {invoice.attachment.media_type === "application/pdf"
                      ? "PDF"
                      : invoice.attachment.media_type === "application/xml"
                        ? "UBL XML"
                        : "صورة"}
                  </p>
                </div>
                <ShieldCheck size={21} className="teal-text" />
              </div>
              <div className="file-preview">
                {invoice.attachment.media_type.startsWith("image/") ? (
                  <img src={invoice.attachment.url} alt="الملف الأصلي للفاتورة" />
                ) : invoice.attachment.media_type === "application/xml" ? (
                  <div className="structured-document-placeholder">
                    <FileCode2 size={48} strokeWidth={1.2} />
                    <strong>UBL XML</strong>
                    <span>ملف فاتورة منظم محفوظ بخصوصية.</span>
                  </div>
                ) : (
                  <>
                    <div className="pdf-sheet">
                      <FileText size={56} strokeWidth={1.1} />
                      <span>PDF</span>
                    </div>
                    <strong className="filename">{invoice.attachment.name}</strong>
                    <p>حمّل النسخة الأصلية لفتحها على جهازك.</p>
                  </>
                )}
              </div>
              <div className="preview-actions">
                <Button onClick={download} variant="outline">
                  <Download size={17} />
                  تحميل الملف الأصلي
                </Button>
                {downloadError && (
                  <p className="error-text" role="alert">
                    {downloadError}
                  </p>
                )}
              </div>
            </section>
            <div className="detail-side">
              <section className="surface details-card">
                <h2>بيانات الفاتورة</h2>
                <dl>
                  <div>
                    <dt>المشروع</dt>
                    <dd>
                      <FolderKanban size={17} />
                      {invoice.project.name}
                    </dd>
                  </div>
                  <div>
                    <dt>رمز المشروع</dt>
                    <dd dir="ltr" className="mono">
                      {invoice.project.code}
                    </dd>
                  </div>
                  <div>
                    <dt>رُفعت بواسطة</dt>
                    <dd>{invoice.created_by.name}</dd>
                  </div>
                  <div>
                    <dt>الحالة</dt>
                    <dd>{statusLabels[invoice.status]}</dd>
                  </div>
                  <div>
                    <dt>ملاحظة</dt>
                    <dd className="note-content">{invoice.note || "لا توجد ملاحظة مضافة."}</dd>
                  </div>
                </dl>
              </section>
              <section className="surface timeline-card">
                <h2>سجل الإجراءات</h2>
                <ol>
                  {invoice.events?.map((event) => (
                    <li key={event.id}>
                      <span className="timeline-dot">
                        <Check size={12} />
                      </span>
                      <div>
                        <strong>
                          {event.action === "DRAFT_UPDATED"
                            ? `تحديث بيانات الفاتورة — نسخة ${event.details?.revision}`
                            : eventLabels[event.action] || event.action}
                        </strong>
                        <p>{event.actor_name}</p>
                        <time dateTime={event.created_at}>{formatDate(event.created_at)}</time>
                        {event.details?.from_status && event.details?.to_status && (
                          <p>
                            {statusLabels[event.details.from_status]} ←{" "}
                            {statusLabels[event.details.to_status]}
                          </p>
                        )}
                        {event.details?.comment && (
                          <p className="note-content">{event.details.comment}</p>
                        )}
                        {event.details?.snapshot && (
                          <details className="audit-change">
                            <summary>بيانات الفاتورة وقت الإجراء</summary>
                            <p>
                              نسخة الإرسال {event.details.submitted_revision} · نسخة الإجراء{" "}
                              {event.details.revision}
                            </p>
                            <InvoiceDataView data={event.details.snapshot} showNote />
                            {event.details.audit_snapshot && (
                              <InvoiceAuditPanel
                                audit={event.details.audit_snapshot}
                                currency={event.details.snapshot.currency}
                                compact
                              />
                            )}
                          </details>
                        )}
                        {event.details?.before && event.details?.after && (
                          <details className="audit-change">
                            <summary>عرض التغييرات</summary>
                            <div className="audit-snapshots">
                              <section>
                                <h3>قبل التعديل</h3>
                                <InvoiceDataView data={event.details.before} showNote />
                              </section>
                              <section>
                                <h3>بعد التعديل</h3>
                                <InvoiceDataView data={event.details.after} showNote />
                              </section>
                            </div>
                          </details>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
