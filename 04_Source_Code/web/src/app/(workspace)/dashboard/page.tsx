"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ChartNoAxesCombined,
  CircleAlert,
  CircleDollarSign,
  Clock3,
  FileCheck2,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { amount } from "@/components/invoice-financial";
import { InvoiceStatusBadge } from "@/components/invoice-workflow";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import {
  api,
  statusLabels,
  type Currency,
  type DashboardData,
  type InvoiceStatus,
} from "@/lib/api";

const currencies: Currency[] = ["SAR", "AED", "USD", "EUR"];
const riskLabels = { LOW: "منخفضة", MEDIUM: "متوسطة", HIGH: "مرتفعة" } as const;

function monthLabel(key: string) {
  const [year, month] = key.split("-").map(Number);
  return new Intl.DateTimeFormat("ar-SA", { month: "short", year: "numeric" }).format(
    new Date(Date.UTC(year, month - 1, 1)),
  );
}

function Bar({ value, maximum, tone = "teal" }: { value: number; maximum: number; tone?: string }) {
  const width = maximum ? Math.max(value === 0 ? 0 : 3, (Math.abs(value) / maximum) * 100) : 0;
  return (
    <span className={`dashboard-bar ${tone} ${value < 0 ? "negative" : ""}`} aria-hidden="true">
      <i style={{ width: `${Math.min(width, 100)}%` }} />
    </span>
  );
}

export default function DashboardPage() {
  const { user } = useSession();
  const [currency, setCurrency] = useState<Currency>("SAR");
  const [projectId, setProjectId] = useState("");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (user.role === "EMPLOYEE") return;
    let active = true;
    setData(null);
    setError("");
    const query = new URLSearchParams({ currency });
    if (projectId) query.set("project_id", projectId);
    api<DashboardData>(`/analytics/dashboard?${query}`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((failure) => {
        if (active) setError(failure.message);
      });
    return () => {
      active = false;
    };
  }, [attempt, currency, projectId, user.role]);

  const maximum = useMemo(() => {
    if (!data) return 0;
    const values = [
      ...data.monthly_approved_net.map((item) => Math.abs(Number(item.amount))),
      ...data.project_breakdown.flatMap((item) => [
        Math.abs(Number(item.approved_net)),
        Math.abs(Number(item.under_review_net)),
      ]),
      ...data.supplier_breakdown.map((item) => Math.abs(Number(item.approved_net))),
    ];
    return Math.max(...values, 0);
  }, [data]);

  if (user.role === "EMPLOYEE")
    return (
      <div className="page-container">
        <div className="surface inline-state">
          <h1>اللوحة المالية مخصصة للمراجعين</h1>
          <Link href="/invoices">العودة إلى الفواتير</Link>
        </div>
      </div>
    );

  return (
    <div className="page-container dashboard-page">
      <div className="page-heading dashboard-heading">
        <div>
          <span className="eyebrow">التحليل المالي</span>
          <h1>لوحة المصروفات والاستثناءات</h1>
          <p>أرقام قابلة للتتبع إلى المستند، مع فصل العملات والمعتمد عن قيد المراجعة.</p>
        </div>
        <span className="feature-icon">
          <ChartNoAxesCombined size={25} />
        </span>
      </div>

      <div className="surface dashboard-filters" aria-label="مرشحات اللوحة">
        <div className="field">
          <label htmlFor="dashboard-currency">العملة</label>
          <select
            id="dashboard-currency"
            className="form-field"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as Currency)}
          >
            {currencies.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="dashboard-project">المشروع</label>
          <select
            id="dashboard-project"
            className="form-field"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
          >
            <option value="">كل المشاريع المتاحة</option>
            {data?.projects.map((project) => (
              <option value={project.id} key={project.id}>
                {project.name} ({project.code})
              </option>
            ))}
          </select>
        </div>
        <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>
          <RefreshCw size={16} /> تحديث
        </Button>
      </div>

      {error ? (
        <div className="surface inline-state">
          <p className="error-text" role="alert">
            {error}
          </p>
          <Button variant="outline" onClick={() => setAttempt((value) => value + 1)}>
            إعادة المحاولة
          </Button>
        </div>
      ) : !data ? (
        <div className="surface inline-state" role="status">
          <LoaderCircle className="animate-spin" /> جارٍ حساب اللوحة…
        </div>
      ) : (
        <>
          <section className="dashboard-metrics" aria-label="ملخص اللوحة">
            <article className="surface dashboard-metric">
              <span className="metric-icon">
                <FileCheck2 size={21} />
              </span>
              <div>
                <small>صافي المعتمد</small>
                <strong>{amount(data.summary.approved_net, data.currency)}</strong>
                <p>{data.summary.approved_document_count} مستندات</p>
              </div>
            </article>
            <article className="surface dashboard-metric">
              <span className="metric-icon sand">
                <Clock3 size={21} />
              </span>
              <div>
                <small>صافي قيد المراجعة</small>
                <strong>{amount(data.summary.under_review_net, data.currency)}</strong>
                <p>{data.summary.under_review_document_count} مستندات</p>
              </div>
            </article>
            <article className="surface dashboard-metric">
              <span className="metric-icon warn">
                <CircleAlert size={21} />
              </span>
              <div>
                <small>استثناءات مفتوحة</small>
                <strong>{data.summary.exception_count.toLocaleString("ar-SA")}</strong>
                <p>{data.summary.high_risk_count} بأولوية مرتفعة</p>
              </div>
            </article>
            <article className="surface dashboard-metric">
              <span className="metric-icon blue">
                <CircleDollarSign size={21} />
              </span>
              <div>
                <small>المستندات ضمن المرشح</small>
                <strong>{data.summary.document_count.toLocaleString("ar-SA")}</strong>
                <p>العملة {data.currency}</p>
              </div>
            </article>
          </section>

          <div className="dashboard-grid">
            <section className="surface dashboard-section dashboard-exceptions">
              <div className="dashboard-section-heading">
                <div>
                  <span className="eyebrow">قائمة العمل</span>
                  <h2>الاستثناءات ذات الأولوية</h2>
                </div>
                <ShieldAlert size={22} />
              </div>
              {data.exception_queue.length === 0 ? (
                <div className="dashboard-empty">
                  لا توجد مستندات قيد المراجعة تحمل عوامل مخاطر.
                </div>
              ) : (
                <div className="exception-list">
                  {data.exception_queue.map((item) => (
                    <Link href={`/invoices/${item.invoice_id}`} key={item.invoice_id}>
                      <span className={`risk-dot risk-${item.risk.level.toLowerCase()}`} />
                      <div>
                        <strong>{item.invoice_number || "مستند دون رقم"}</strong>
                        <p>
                          {item.supplier_name || "مورد غير محدد"} · {item.project.name}
                        </p>
                        <small>{item.top_reason}</small>
                      </div>
                      <div className="exception-score">
                        <strong>{item.risk.score}</strong>
                        <span>{riskLabels[item.risk.level]}</span>
                        <InvoiceStatusBadge status={item.status} />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </section>

            <section className="surface dashboard-section">
              <div className="dashboard-section-heading">
                <div>
                  <span className="eyebrow">آخر ستة أشهر</span>
                  <h2>صافي المعتمد شهريًا</h2>
                </div>
              </div>
              <div className="dashboard-bars">
                {data.monthly_approved_net.map((item) => (
                  <div key={item.month}>
                    <span>{monthLabel(item.month)}</span>
                    <Bar value={Number(item.amount)} maximum={maximum} />
                    <strong>{amount(item.amount, data.currency)}</strong>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="dashboard-grid equal">
            <section className="surface dashboard-section">
              <div className="dashboard-section-heading">
                <div>
                  <span className="eyebrow">المشاريع</span>
                  <h2>المعتمد وقيد المراجعة</h2>
                </div>
              </div>
              {data.project_breakdown.map((item) => (
                <article className="project-analysis-row" key={item.project.id}>
                  <div>
                    <strong>{item.project.name}</strong>
                    <small>
                      {item.document_count} مستندات · {item.exception_count} استثناءات
                    </small>
                  </div>
                  <div>
                    <span>معتمد</span>
                    <Bar value={Number(item.approved_net)} maximum={maximum} />
                    <bdi>{amount(item.approved_net, data.currency)}</bdi>
                  </div>
                  <div>
                    <span>قيد المراجعة</span>
                    <Bar value={Number(item.under_review_net)} maximum={maximum} tone="sand" />
                    <bdi>{amount(item.under_review_net, data.currency)}</bdi>
                  </div>
                </article>
              ))}
            </section>

            <section className="surface dashboard-section">
              <div className="dashboard-section-heading">
                <div>
                  <span className="eyebrow">الموردون</span>
                  <h2>أعلى صافي معتمد</h2>
                </div>
              </div>
              {data.supplier_breakdown.length === 0 ? (
                <div className="dashboard-empty">لا توجد مستندات معتمدة بهذه العملة بعد.</div>
              ) : (
                <div className="supplier-analysis-list">
                  {data.supplier_breakdown.map((item) => (
                    <div key={item.supplier_name}>
                      <span>{item.supplier_name}</span>
                      <Bar value={Number(item.approved_net)} maximum={maximum} />
                      <strong>{amount(item.approved_net, data.currency)}</strong>
                      <small>{item.document_count} مستندات</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="surface dashboard-section status-analysis">
            <div className="dashboard-section-heading">
              <div>
                <span className="eyebrow">حالة الدورة</span>
                <h2>توزيع المستندات</h2>
              </div>
            </div>
            <div>
              {(Object.entries(data.status_counts) as [InvoiceStatus, number][]).map(
                ([status, count]) => (
                  <article key={status}>
                    <span>{statusLabels[status]}</span>
                    <strong>{count.toLocaleString("ar-SA")}</strong>
                  </article>
                ),
              )}
            </div>
          </section>

          <div className="surface dashboard-definitions">
            <strong>تعريف الأرقام</strong>
            <p>{data.definitions.approved_net}</p>
            <p>{data.definitions.under_review_net}</p>
            <p>{data.definitions.currency}</p>
            <small>آخر حساب: {new Date(data.generated_at).toLocaleString("ar-SA")}</small>
          </div>
        </>
      )}
    </div>
  );
}
