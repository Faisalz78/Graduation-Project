"use client";

import { useEffect, useState } from "react";
import { FileCode2, FileSearch, LoaderCircle, QrCode } from "lucide-react";
import { api, type ExtractionJob, type ExtractionSuggestion, type Invoice } from "@/lib/api";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";

const labels: Record<string, string> = {
  supplier_name: "اسم المورد",
  invoice_number: "رقم الفاتورة",
  invoice_date: "التاريخ",
  currency: "العملة",
  subtotal: "المجموع قبل الضريبة",
  tax_total: "إجمالي الضريبة",
  grand_total: "الإجمالي المستحق",
  description: "الوصف",
  quantity: "الكمية",
  unit_price: "سعر الوحدة",
  discount_amount: "الخصم",
  tax_rate: "الضريبة %",
  document_total: "إجمالي البند في المستند",
  supplier_tax_number: "الرقم الضريبي للمورد",
  invoice_timestamp: "وقت إصدار الفاتورة",
};
const states = {
  QUEUED: "في انتظار القراءة",
  RUNNING: "جارٍ استخراج البيانات…",
  SUCCEEDED: "الاقتراحات جاهزة للمراجعة",
  FAILED: "تعذرت القراءة",
  STALE: "تغيرت الفاتورة بعد طلب القراءة",
};

const sourceNames = {
  OCR: "قراءة من الصورة",
  PDF_TEXT: "نص موجود داخل PDF",
  QR: "بيانات ZATCA TLV من QR",
  XML: "بيانات منظمة من UBL XML",
} as const;

export function InvoiceExtraction({
  invoice,
  disabled,
  onImport,
}: {
  invoice: Invoice;
  disabled: boolean;
  onImport: (job: ExtractionJob) => void;
}) {
  const { csrf_token } = useSession();
  const [job, setJob] = useState<ExtractionJob | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [language, setLanguage] = useState<"ar" | "en">("ar");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [evidence, setEvidence] = useState<ExtractionSuggestion | null>(null);
  const [previewError, setPreviewError] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api<{ available: boolean; job: ExtractionJob | null }>(
          `/invoices/${invoice.id}/extraction`,
        );
        if (!active) return;
        setJob(data.job);
        setAvailable(data.available);
        setError("");
        if (data.job?.status === "QUEUED" || data.job?.status === "RUNNING")
          timer = setTimeout(load, 2000);
      } catch (failure) {
        if (active) setError((failure as Error).message);
      }
    }
    setJob(null);
    setEvidence(null);
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [invoice.id, invoice.revision, refresh]);
  const running = job?.status === "QUEUED" || job?.status === "RUNNING";
  const stale = job?.is_stale || (job && job.base_revision !== invoice.revision);
  async function start() {
    setBusy(true);
    setError("");
    setEvidence(null);
    try {
      const data = await api<ExtractionJob>(`/invoices/${invoice.id}/extraction`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf_token },
        body: JSON.stringify({
          revision: invoice.revision,
          language,
          force: job?.status === "SUCCEEDED",
        }),
      });
      setJob(data);
      setRefresh((n) => n + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function value(suggestion: ExtractionSuggestion | undefined) {
    if (!suggestion) return <span className="extraction-missing">لم يُقرأ</span>;
    return (
      <button
        type="button"
        className="extraction-value"
        onClick={() => setEvidence(suggestion)}
        title="عرض الدليل في الأصل"
      >
        <bdi>{suggestion.value}</bdi>
        {suggestion.confidence !== null && suggestion.confidence < 0.9 && (
          <small>راجع بعناية</small>
        )}
      </button>
    );
  }
  return (
    <section className="surface extraction-panel" aria-label="استخراج بيانات الفاتورة">
      <div className="extraction-heading">
        <div>
          <span className="eyebrow">قراءة مساعدة · تجريبية</span>
          <h2>
            <FileSearch size={21} /> استخراج بيانات الفاتورة
          </h2>
          <p>
            اقرأ الأصل آليًا، ثم راجع الاقتراحات وصححها. القراءة لا تحفظ بيانات الفاتورة ولا ترسلها
            للموافقة.
          </p>
        </div>
        <div className="extraction-controls">
          <label htmlFor="extraction-language">لغة الفاتورة</label>
          <select
            id="extraction-language"
            className="form-field"
            value={language}
            disabled={busy || running || disabled}
            onChange={(e) => setLanguage(e.target.value as "ar" | "en")}
          >
            <option value="ar">عربي / مختلط</option>
            <option value="en">الإنجليزية</option>
          </select>
          <Button
            type="button"
            disabled={!available || busy || running || disabled}
            onClick={start}
          >
            {busy || running ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <FileSearch size={16} />
            )}
            {job?.status === "FAILED" || job?.status === "SUCCEEDED" || stale
              ? "إعادة قراءة الفاتورة"
              : "استخراج البيانات"}
          </Button>
        </div>
      </div>
      {available === false && !error && (
        <p className="field-hint">محرك القراءة غير مهيأ. يمكنك متابعة الإدخال اليدوي.</p>
      )}
      {job && (
        <p role="status" className="extraction-status">
          {stale ? "تغيرت الفاتورة؛ أعد القراءة للنسخة الحالية." : states[job.status]}
        </p>
      )}
      {running && (
        <p className="field-hint">
          قد تستغرق قراءة الأجزاء والجداول عدة دقائق. يمكنك متابعة التحرير. إذا حفظت تعديلًا أثناء
          القراءة فستحتاج قراءة جديدة. الطلب محفوظ حتى لو أغلقت الصفحة.
        </p>
      )}
      {job?.error && (
        <p className="error-box" role="alert">
          {job.error}
        </p>
      )}
      {error && (
        <div className="error-box" role="alert">
          {error}
          <Button type="button" variant="outline" onClick={() => setRefresh((n) => n + 1)}>
            تحديث حالة القراءة
          </Button>
        </div>
      )}
      {job?.result && !stale && (
        <>
          {!!job.result.page_routes?.length && (
            <div className="extraction-notice" aria-label="طريقة قراءة الصفحات">
              {job.result.page_routes.map((route) => (
                <p key={route.page}>
                  الصفحة {route.page}:{" "}
                  {route.method === "PDF_TEXT"
                    ? "قراءة النص مباشرة من PDF"
                    : route.method === "BLANK"
                      ? "صفحة فارغة"
                      : "قراءة من الصورة"}
                  {route.reason === "DIRECT_EXTRACTION_FAILED" || route.reason === "UNUSABLE_TEXT"
                    ? " — استُخدمت الصورة لتعذر قراءة النص مباشرة."
                    : ""}
                </p>
              ))}
            </div>
          )}
          {job.result.local_understanding &&
            job.result.local_understanding.status !== "NOT_APPLICABLE" && (
              <div className="extraction-notice" aria-label="الفهم البصري المحلي">
                <p>
                  {job.result.local_understanding.status === "UNAVAILABLE"
                    ? "تعذر تشغيل الفهم البصري المحلي؛ هذه اقتراحات قراءة النص فقط. يمكنك إعادة القراءة بعد تشغيل النموذج."
                    : job.result.local_understanding.status === "PARTIAL"
                      ? "اكتمل الفهم البصري المحلي لبعض الصفحات فقط؛ راجع بقية الصفحات من الأصل."
                      : "اكتمل الفهم البصري على جهازك. لم تُرسل الفاتورة إلى خدمة خارجية."}
                </p>
                {job.result.local_understanding.pages > 0 && (
                  <p>
                    أضاف {job.result.local_understanding.added_fields} حقول و
                    {job.result.local_understanding.added_rows} بنود، ووافق القراءة السابقة في{" "}
                    {job.result.local_understanding.confirmed_fields} حقول. هذه اقتراحات تحتاج
                    مراجعتك.
                  </p>
                )}
                {job.result.local_understanding.conflicts > 0 && (
                  <p role="alert">
                    اختلف الفهم البصري مع القراءة أو الحسابات في بعض القيم. احتُفظ بالاقتراحات
                    السابقة؛ راجع الأصل، خصوصًا المبالغ.
                  </p>
                )}
                {job.result.local_understanding.rejected_values > 0 && (
                  <p>استُبعدت اقتراحات لم يتوفر لها دليل كافٍ في النص المقروء.</p>
                )}
              </div>
            )}
          {(job.result.warnings.includes("CAMERA_LOW_RESOLUTION") ||
            job.result.warnings.includes("CAMERA_BLUR_POSSIBLE")) && (
            <p className="extraction-notice">
              قد تكون الصورة صغيرة أو غير واضحة. إذا نقصت البيانات، صوّر الورقة كاملة بإضاءة جيدة
              ومن دون اهتزاز، ثم ارفع الصورة الأصلية.
            </p>
          )}
          <div className="extraction-review-grid">
            <div>
              {job.result.image_preparation?.some(
                (entry) => entry.rotation || entry.curvature_corrected,
              ) && (
                <p className="field-hint">
                  صُحح اتجاه الصفحة أو انحناؤها أثناء القراءة. المعاينة والأدلة تشير إلى الملف
                  الأصلي.
                </p>
              )}
              {job.result.guided_reading && (
                <div className="extraction-notice" aria-label="قراءة أجزاء الفاتورة">
                  <p>
                    {job.result.guided_reading.status === "COMPLETED"
                      ? job.result.guided_reading.completed > 0
                        ? `اكتملت قراءة ${job.result.guided_reading.completed} أجزاء، منها ${job.result.guided_reading.table_sections} أجزاء للجدول.`
                        : "لم تُحدد مناطق إضافية للقراءة. راجع الاقتراحات والأصل."
                      : "لم تكتمل قراءة جميع الأجزاء. الاقتراحات المتاحة محفوظة؛ راجع الأجزاء الناقصة من الأصل."}
                  </p>
                </div>
              )}
              {!!job.result.conflict_details?.length && (
                <div aria-label="مقارنة القراءات المختلفة">
                  <h3>قيم تحتاج حسمًا منك</h3>
                  <p className="field-hint">
                    اضغط كل قراءة لعرض موضعها في الأصل، ثم صحح الحقل بنفسك. لم تستبدل القراءة
                    المختلفة بياناتك.
                  </p>
                  {job.result.conflict_details.map((detail, index) => (
                    <article className="extraction-notice" key={index}>
                      <strong>
                        {labels[detail.field] || detail.field}
                        {detail.row ? ` · البند ${detail.row}` : ""}
                      </strong>
                      {detail.reason === "ROW_TOTAL_MISMATCH" ? (
                        <p>
                          القيمة المطبوعة لا تتفق مع حساب البند المقروء. راجع الكمية والسعر والخصم
                          ونسبة الضريبة.
                        </p>
                      ) : null}
                      <dl className="extraction-fields">
                        {detail.current && (
                          <div>
                            <dt>القراءة الحالية</dt>
                            <dd>{value(detail.current)}</dd>
                          </div>
                        )}
                        <div>
                          <dt>القراءة التي تحتاج مراجعة</dt>
                          <dd>{value(detail.proposed)}</dd>
                        </div>
                      </dl>
                    </article>
                  ))}
                </div>
              )}
              <h3>اقتراحات من المستند</h3>
              <p className="field-hint">
                اضغط أي قيمة لعرض دليلها. قد تخطئ القراءة حتى مع درجة محرك مرتفعة.
              </p>
              <dl className="extraction-fields">
                {Object.entries(labels)
                  .slice(0, 7)
                  .map(([name, label]) => (
                    <div key={name}>
                      <dt>{label}</dt>
                      <dd>{value(job.result!.fields[name])}</dd>
                    </div>
                  ))}
              </dl>
              {job.result.warnings.length > 0 && (
                <p className="extraction-notice">
                  توجد حقول تحتاج انتباهًا: قد يكون عنوانها تقريبيًا، أو قرئت بأكثر من محاولة، أو
                  تعذر تحديدها. راجع القيم والأصل قبل الاستخدام.
                </p>
              )}
              {job.result.warnings.includes("DOCUMENT_TOTALS_DO_NOT_RECONCILE") && (
                <p className="error-box">
                  المجموع قبل الضريبة والضريبة لا يطابقان الإجمالي المقروء. راجع المبالغ والخصومات
                  في الأصل.
                </p>
              )}
              {(job.result.structured_sources?.length || 0) > 0 && (
                <div className="structured-sources">
                  <h3>المصادر المنظمة ({job.result.structured_sources?.length})</h3>
                  <p className="field-hint">
                    تُعرض القيم كما قُرئت من QR أو XML للمقارنة. وجودها لا يثبت أصالة المستند.
                  </p>
                  <div className="structured-source-list">
                    {job.result.structured_sources?.map((source, index) => (
                      <article key={`${source.type}:${source.name || source.page}:${index}`}>
                        <div className="structured-source-heading">
                          {source.type === "QR" ? <QrCode size={18} /> : <FileCode2 size={18} />}
                          <strong>{source.type === "QR" ? "رمز QR" : "ملف UBL XML"}</strong>
                          <span>
                            {source.location === "DOCUMENT_PAGE"
                              ? `صفحة ${source.page}`
                              : source.location === "PDF_ATTACHMENT"
                                ? "مرفق داخل PDF"
                                : "الملف المرفوع"}
                          </span>
                        </div>
                        <dl>
                          {Object.entries(source.fields).map(([name, entry]) => (
                            <div key={name}>
                              <dt>{labels[name] || name}</dt>
                              <dd dir="auto">{entry.value}</dd>
                            </div>
                          ))}
                        </dl>
                      </article>
                    ))}
                  </div>
                </div>
              )}
              <h3>البنود المقترحة ({job.result.items.length})</h3>
              {job.result.items.length === 0 ? (
                <p>لم تُحدد البنود بشكل موثوق. أدخلها يدويًا.</p>
              ) : (
                <div className="extraction-table-wrap">
                  <table className="extraction-table">
                    <thead>
                      <tr>
                        {[
                          "description",
                          "quantity",
                          "unit_price",
                          "discount_amount",
                          "tax_rate",
                        ].map((k) => (
                          <th key={k}>{labels[k]}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {job.result.items.map((item, index) => (
                        <tr key={index}>
                          {[
                            "description",
                            "quantity",
                            "unit_price",
                            "discount_amount",
                            "tax_rate",
                          ].map((k) => (
                            <td key={k}>{value(item[k])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <aside className="extraction-evidence">
              <h3>الأصل والدليل</h3>
              {invoice.attachment.media_type === "application/xml" ? (
                <div className="structured-document-placeholder">
                  <FileCode2 size={44} />
                  <strong>UBL XML</strong>
                  <span>راجع القيم المنظمة ثم حمّل الأصل عند الحاجة.</span>
                </div>
              ) : (
                <div className="extraction-image">
                  <img
                    src={
                      invoice.attachment.media_type.startsWith("image/")
                        ? `${invoice.attachment.url}?inline=true`
                        : `/api/v1/invoices/${invoice.id}/preview/${evidence?.page || 1}`
                    }
                    alt="الفاتورة الأصلية مع موضع الدليل"
                    onLoad={() => setPreviewError(false)}
                    onError={() => setPreviewError(true)}
                  />
                  {evidence?.bbox && !previewError && (
                    <span
                      className="evidence-box"
                      style={{
                        left: `${evidence.bbox[0] * 100}%`,
                        top: `${evidence.bbox[1] * 100}%`,
                        width: `${(evidence.bbox[2] - evidence.bbox[0]) * 100}%`,
                        height: `${(evidence.bbox[3] - evidence.bbox[1]) * 100}%`,
                      }}
                    />
                  )}
                </div>
              )}
              {previewError && (
                <p className="error-box">تعذرت معاينة الصفحة. حمّل الأصل للمراجعة.</p>
              )}
              {evidence ? (
                <div className="evidence-text">
                  <strong>
                    الدليل{evidence.page !== null ? ` · صفحة ${evidence.page}` : " · XML"}
                  </strong>
                  <p dir="auto">{evidence.evidence}</p>
                  <p>
                    {sourceNames[evidence.source]}
                    {evidence.confidence !== null &&
                      ` · درجة المحرك ${Math.round(evidence.confidence * 100)}%`}
                  </p>
                  <small>درجة المحرك ليست ضمانًا لصحة القيمة.</small>
                </div>
              ) : (
                <p className="field-hint">اختر قيمة لعرض نص الدليل وصفحته.</p>
              )}
              <a href={invoice.attachment.url} download>
                تحميل الأصل للمراجعة
              </a>
            </aside>
          </div>
          <div className="extraction-import">
            <Button type="button" disabled={disabled} onClick={() => onImport(job)}>
              نقل الاقتراحات للحقول الفارغة
            </Button>
            <p>
              تبقى قيمك الحالية كما هي. تُنقل البنود فقط إذا كانت قائمتك فارغة. اختر المورد بنفسك،
              ثم راجع البيانات وأكدها قبل الحفظ. الإجماليات المقروءة مرجع للمقارنة؛ تحسب إجماليات
              النموذج من البنود.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
