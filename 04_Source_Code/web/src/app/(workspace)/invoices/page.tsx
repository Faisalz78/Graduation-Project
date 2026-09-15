"use client";
import { amount } from "@/components/invoice-financial";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpLeft,
  FilePlus2,
  Files,
  FolderKanban,
  LoaderCircle,
  Plus,
  ReceiptText,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/components/session-provider";
import { api, statusLabels, type InvoiceStatus, type InvoicePage, type Project } from "@/lib/api";
import { InvoiceStatusBadge } from "@/components/invoice-workflow";
import { fileSize, formatDate } from "@/lib/utils";

export default function InvoicesPage() {
  const { user } = useSession();
  const [data, setData] = useState<InvoicePage | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<InvoiceStatus | "">(
    user.role === "PROJECT_MANAGER"
      ? "PROJECT_REVIEW"
      : user.role === "FINANCE_MANAGER"
        ? "FINANCE_REVIEW"
        : "",
  );
  useEffect(() => {
    let active = true;
    setError("");
    setData(null);
    Promise.all([
      api<InvoicePage>(`/invoices?page=${page}${status ? `&status=${status}` : ""}`),
      api<Project[]>("/projects"),
    ])
      .then(([invoices, projects]) => {
        if (active) {
          setData(invoices);
          setProjects(projects);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [page, attempt, status]);
  const employee = user.role === "EMPLOYEE";
  return (
    <div className="page-container">
      <div className="page-heading">
        <div>
          <span className="eyebrow">الفواتير والمستندات</span>
          <h1>{employee ? "فواتيرك، بوضوح." : "مراجعة الفواتير"}</h1>
          <p>
            {employee
              ? "ارفع فواتير مشاريعك واحتفظ بكل تفاصيلها في مكان واحد."
              : "الفواتير المتاحة لك تظهر هنا وفق دورك ونطاق مشاريعك."}
          </p>
        </div>
        {employee && (
          <Button asChild>
            <Link href="/invoices/new">
              <Plus size={18} />
              رفع فاتورة
            </Link>
          </Button>
        )}
      </div>
      <div className="overview-grid">
        <div className="overview-item">
          <div>
            <span>{status ? "الفواتير في الحالة المختارة" : "الفواتير المتاحة"}</span>
            <strong>{data ? data.total.toLocaleString("ar-SA") : "—"}</strong>
          </div>
          <div className="metric-icon">
            <Files size={23} />
          </div>
        </div>
        <div className="overview-item">
          <div>
            <span>المشاريع المتاحة</span>
            <strong>{data ? projects.length.toLocaleString("ar-SA") : "—"}</strong>
          </div>
          <div className="metric-icon sand">
            <FolderKanban size={23} />
          </div>
        </div>
        <div className="overview-note">
          <span className="small-circle">
            <ReceiptText size={19} />
          </span>
          <div>
            <strong>الأصل محفوظ دائمًا</strong>
            <p>كل فاتورة مرتبطة بملفها ومشروعها وسجل إجراءاتها.</p>
          </div>
        </div>
      </div>
      <section className="surface invoice-surface">
        <div className="surface-heading">
          <div>
            <h2>{employee ? "سجل الفواتير" : "الفواتير المتاحة"}</h2>
            <p>{data ? `${data.total.toLocaleString("ar-SA")} فاتورة` : "جارٍ تحميل السجل"}</p>
          </div>
          <div className="invoice-filter">
            <label htmlFor="invoice-status-filter">تصفية بالحالة</label>
            <select
              id="invoice-status-filter"
              className="form-field"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as InvoiceStatus | "");
                setPage(1);
              }}
            >
              <option value="">كل الحالات</option>
              {(Object.entries(statusLabels) as [InvoiceStatus, string][])
                .filter(([value]) => employee || value !== "DRAFT")
                .map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
            </select>
          </div>
        </div>
        {error ? (
          <div className="inline-state">
            <p className="error-text" role="alert">
              {error}
            </p>
            <Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>
              <RefreshCw size={16} />
              إعادة المحاولة
            </Button>
          </div>
        ) : !data ? (
          <div className="inline-state" role="status">
            <LoaderCircle size={24} className="animate-spin" />
            جارٍ تحميل الفواتير…
          </div>
        ) : data.items.length === 0 ? (
          <div className="empty-state">
            <div className="empty-illustration">
              <div className="empty-orbit" />
              <FilePlus2 size={37} strokeWidth={1.3} />
            </div>
            <h3>
              {status
                ? "لا توجد فواتير بهذه الحالة"
                : employee
                  ? "ابدأ بفاتورتك الأولى"
                  : "لا توجد فواتير متاحة للمراجعة"}
            </h3>
            <p>
              {status
                ? "اختر حالة أخرى أو اعرض كل الحالات من القائمة أعلاه."
                : employee
                  ? "ارفع صورة أو ملف PDF أو UBL XML، واختر المشروع المرتبط به.\nستجد المسودة هنا بعد حفظها."
                  : "تظهر الفواتير هنا بعد إرسال الموظفين لها، وفق نطاق صلاحياتك."}
            </p>
            {employee && (
              <Button asChild variant="outline">
                <Link href="/invoices/new">
                  رفع أول فاتورة <ArrowLeft size={16} />
                </Link>
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>الفاتورة</th>
                    <th>المشروع</th>
                    <th>تاريخ الرفع</th>
                    <th>الحالة</th>
                    <th>
                      <span className="sr-only">فتح</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((invoice) => (
                    <tr key={invoice.id}>
                      <td>
                        <Link href={`/invoices/${invoice.id}`} className="file-cell">
                          <span className="file-icon">
                            <ReceiptText size={21} strokeWidth={1.6} />
                          </span>
                          <span>
                            <strong className="filename">{invoice.attachment.name}</strong>
                            {(invoice.invoice_number || invoice.totals) && (
                              <small className="invoice-list-total">
                                {invoice.invoice_number || "دون رقم"} ·{" "}
                                <bdi>
                                  {invoice.totals
                                    ? amount(invoice.totals.grand_total, invoice.currency)
                                    : "دون إجمالي"}
                                </bdi>
                              </small>
                            )}
                            <small>
                              {invoice.attachment.media_type === "application/pdf"
                                ? "PDF"
                                : invoice.attachment.media_type === "application/xml"
                                  ? "XML"
                                  : "صورة"}{" "}
                              · {fileSize(invoice.attachment.size_bytes)}
                            </small>
                          </span>
                        </Link>
                      </td>
                      <td>
                        <span className="project-label">{invoice.project.name}</span>
                        <small className="table-code" dir="ltr">
                          {invoice.project.code}
                        </small>
                      </td>
                      <td className="date-cell">{formatDate(invoice.created_at)}</td>
                      <td>
                        <InvoiceStatusBadge status={invoice.status} />
                      </td>
                      <td>
                        <Link
                          className="open-invoice"
                          href={`/invoices/${invoice.id}`}
                          aria-label={`فتح ${invoice.attachment.name}`}
                        >
                          <ArrowUpLeft size={19} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.total > data.page_size && (
              <div className="pagination">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage(page - 1)}
                >
                  السابق
                </Button>
                <span>صفحة {page.toLocaleString("ar-SA")}</span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page * data.page_size >= data.total}
                  onClick={() => setPage(page + 1)}
                >
                  التالي
                </Button>
              </div>
            )}
          </>
        )}
      </section>
      <div className="bottom-hint">
        <span className="status-dot" />
        <span>
          {employee
            ? "المسودات خاصة بك حتى ترسلها. تابع طلبات التعديل وقرارات المراجعة من هنا."
            : "يعرض السجل فواتير نطاقك. اختر كل الحالات للاطلاع على القرارات السابقة."}
        </span>
      </div>
    </div>
  );
}
