"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { FileDown, FileSpreadsheet, LoaderCircle, RotateCcw, WalletCards } from "lucide-react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { api, statusLabels, type Currency, type InvoiceStatus, type Project } from "@/lib/api";

const currencies: Currency[] = ["SAR", "AED", "USD", "EUR"];
const reportStatuses: InvoiceStatus[] = [
  "PROJECT_REVIEW",
  "FINANCE_REVIEW",
  "CHANGES_REQUESTED",
  "APPROVED",
  "REJECTED",
];

export default function ReportsPage() {
  const { user } = useSession();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [currency, setCurrency] = useState<"" | Currency>("");
  const [status, setStatus] = useState<"" | InvoiceStatus>("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    if (user.role === "EMPLOYEE") return;
    api<Project[]>("/projects")
      .then(setProjects)
      .catch((failure) => setError((failure as Error).message));
  }, [user.role]);

  const invoiceQuery = useMemo(() => {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (currency) query.set("currency", currency);
    if (status) query.set("status", status);
    if (dateFrom) query.set("date_from", dateFrom);
    if (dateTo) query.set("date_to", dateTo);
    return query.toString();
  }, [projectId, currency, status, dateFrom, dateTo]);

  const budgetQuery = useMemo(() => {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (currency) query.set("currency", currency);
    return query.toString();
  }, [projectId, currency]);

  function reportUrl(path: string, query: string) {
    return "/api/v1/reports/" + path + (query ? "?" + query : "");
  }

  function reset() {
    setProjectId("");
    setCurrency("");
    setStatus("");
    setDateFrom("");
    setDateTo("");
  }

  if (user.role === "EMPLOYEE")
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>التقارير مخصصة للمراجعين</h1>
          <Link href="/invoices">العودة إلى الفواتير</Link>
        </div>
      </div>
    );

  return (
    <div className="page-container reports-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">ملفات قابلة للتتبع</span>
          <h1>التقارير والتصدير</h1>
          <p>نزّل البيانات المسموح لك برؤيتها بصيغة CSV متوافقة مع Excel.</p>
        </div>
        <span className="feature-icon">
          <FileSpreadsheet size={25} />
        </span>
      </div>

      <section className="surface report-filters" aria-label="مرشحات التقارير">
        <div className="field">
          <label htmlFor="report-project">المشروع</label>
          <select
            id="report-project"
            className="form-field"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            disabled={!projects}
          >
            <option value="">كل المشاريع المتاحة</option>
            {projects?.map((project) => (
              <option value={project.id} key={project.id}>
                {project.name} ({project.code})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="report-currency">العملة</label>
          <select
            id="report-currency"
            className="form-field"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as "" | Currency)}
          >
            <option value="">كل العملات منفصلة في الصفوف</option>
            {currencies.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="report-status">حالة المستند</label>
          <select
            id="report-status"
            className="form-field"
            value={status}
            onChange={(event) => setStatus(event.target.value as "" | InvoiceStatus)}
          >
            <option value="">كل الحالات المتاحة</option>
            {reportStatuses.map((value) => (
              <option value={value} key={value}>
                {statusLabels[value]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="report-from">من تاريخ المستند</label>
          <input
            id="report-from"
            className="form-field"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="report-to">إلى تاريخ المستند</label>
          <input
            id="report-to"
            className="form-field"
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(event) => setDateTo(event.target.value)}
          />
        </div>
        <Button variant="outline" onClick={reset}>
          <RotateCcw size={16} />
          مسح المرشحات
        </Button>
      </section>

      {error ? (
        <div className="surface inline-state">
          <p role="alert">{error}</p>
        </div>
      ) : !projects ? (
        <div className="surface inline-state" role="status">
          <LoaderCircle className="animate-spin" />
          جارٍ تحميل نطاق التقارير…
        </div>
      ) : (
        <section className="report-grid">
          <article className="surface report-card">
            <span className="report-icon">
              <FileSpreadsheet size={22} />
            </span>
            <div>
              <h2>سجل الفواتير</h2>
              <p>المستندات والحالات والمشاريع والموردون والمبالغ، مع درجة آخر قرار مراجعة.</p>
              <small>يطبق جميع المرشحات أعلاه، وبحد أقصى 5,000 مستند.</small>
            </div>
            <Button asChild>
              <a href={reportUrl("invoices.csv", invoiceQuery)} download>
                <FileDown size={17} />
                تنزيل CSV
              </a>
            </Button>
          </article>

          <article className="surface report-card">
            <span className="report-icon sand">
              <FileDown size={22} />
            </span>
            <div>
              <h2>المقارنة الإقليمية</h2>
              <p>نتائج البنود ووسيط منطقة المورد والوسائط المجمعة للمناطق الأخرى.</p>
              <small>يطبق جميع المرشحات أعلاه، وبحد أقصى 500 مستند للتحليل.</small>
            </div>
            <Button asChild>
              <a href={reportUrl("regional-prices.csv", invoiceQuery)} download>
                <FileDown size={17} />
                تنزيل CSV
              </a>
            </Button>
          </article>

          <article className="surface report-card">
            <span className="report-icon blue">
              <WalletCards size={22} />
            </span>
            <div>
              <h2>ملخص ميزانيات المشاريع</h2>
              <p>الإجمالي والمخصص والاحتياطي والمعتمد والملتزم وقيد المراجعة والمتبقي.</p>
              <small>يطبق مرشحي المشروع والعملة فقط.</small>
            </div>
            <Button asChild>
              <a href={reportUrl("budgets.csv", budgetQuery)} download>
                <FileDown size={17} />
                تنزيل CSV
              </a>
            </Button>
          </article>
        </section>
      )}

      <p className="report-note">
        كل عملة تبقى في عمودها دون تحويل. المقارنة الإقليمية من سجل الشركة الداخلي ولا تمثل سعر سوق
        خارجيًا.
      </p>
    </div>
  );
}
