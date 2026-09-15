import { AlertTriangle, CheckCircle2, CircleDashed, Gauge, ShieldCheck } from "lucide-react";
import { amount } from "@/components/invoice-financial";
import { type Currency, type InvoiceAudit } from "@/lib/api";

const summary = {
  PASS: {
    title: "لم تظهر ملاحظات في الفحوص الحالية",
    text: "اكتملت الفحوص المتاحة وتطابقت القيم المدخلة.",
  },
  NEEDS_REVIEW: {
    title: "توجد نتائج تحتاج مراجعة",
    text: "راجع الفروق وارتفاعات الأسعار وإشارات التكرار قبل اتخاذ القرار.",
  },
  INCOMPLETE: {
    title: "بعض الفحوص لم تكتمل",
    text: "أكمل الإجماليات الظاهرة على الأصل والبيانات المطلوبة لإتمام المقارنة.",
  },
} as const;

const status = {
  PASS: { label: "مطابق", Icon: CheckCircle2 },
  WARNING: { label: "يحتاج مراجعة", Icon: AlertTriangle },
  NOT_CHECKED: { label: "غير مكتمل", Icon: CircleDashed },
} as const;

const comparisonStatus = {
  MATCH: "مطابق",
  MISMATCH: "مختلف",
  NOT_COMPARABLE: "البيان المؤكد ناقص",
} as const;
const moneyFields = new Set(["subtotal", "tax_total", "grand_total"]);
const riskLevels = {
  LOW: "منخفضة",
  MEDIUM: "متوسطة",
  HIGH: "مرتفعة",
} as const;
const confidenceLevels = {
  LOW: "منخفضة",
  MEDIUM: "متوسطة",
  HIGH: "مرتفعة",
} as const;

function comparisonValue(field: string, value: string, currency: Currency | null) {
  return moneyFields.has(field) ? amount(value, currency) : value;
}

export function InvoiceAuditPanel({
  audit,
  currency,
  compact = false,
}: {
  audit: InvoiceAudit;
  currency: Currency | null;
  compact?: boolean;
}) {
  const heading = summary[audit.summary];
  return (
    <section className={`${compact ? "audit-panel compact" : "surface audit-panel"}`}>
      <div className="audit-panel-heading">
        <div>
          <h2>{heading.title}</h2>
          <p>{heading.text}</p>
        </div>
        <ShieldCheck size={22} />
      </div>
      {audit.risk && (
        <div className={`risk-summary risk-${audit.risk.level.toLowerCase()}`}>
          <div className="risk-score" aria-label={`درجة أولوية المخاطر ${audit.risk.score} من 100`}>
            <Gauge size={20} />
            <strong>{audit.risk.score}</strong>
            <span>/ 100</span>
          </div>
          <div className="risk-summary-copy">
            <div>
              <strong>أولوية المراجعة {riskLevels[audit.risk.level]}</strong>
              <span>
                موثوقية التغطية {confidenceLevels[audit.risk.confidence]} · فُحصت{" "}
                {audit.risk.evaluated_count} من {audit.risk.total_checks}
              </span>
            </div>
            {audit.risk.factors.length > 0 ? (
              <ul>
                {audit.risk.factors.map((factor) => (
                  <li key={factor.code}>
                    {factor.label} <bdi>+{factor.weight}</bdi>
                  </li>
                ))}
              </ul>
            ) : (
              <p>لم تضف الفحوص المتاحة أي عامل إلى درجة الأولوية.</p>
            )}
            <small>{audit.risk.advisory}</small>
          </div>
        </div>
      )}
      <div className="audit-checks">
        {audit.checks.map((check) => {
          const state = status[check.status];
          return (
            <article key={check.code} className={`audit-check audit-${check.status.toLowerCase()}`}>
              <state.Icon size={19} />
              <div>
                <div className="audit-check-title">
                  <strong>{check.label}</strong>
                  <span>{state.label}</span>
                </div>
                <p>{check.message}</p>
                {check.code !== "SPLIT_INVOICE" &&
                  check.code !== "PROJECT_BUDGET_CAPACITY" &&
                  check.document_value !== null &&
                  check.calculated_value !== null && (
                    <p className="audit-values">
                      الظاهر على الأصل: <bdi>{amount(check.document_value, currency)}</bdi> ·
                      المحسوب: <bdi>{amount(check.calculated_value, currency)}</bdi>
                      {check.difference !== "0.00" && check.difference !== null && (
                        <>
                          {" "}
                          · الفرق: <bdi>{amount(check.difference, currency)}</bdi>
                        </>
                      )}
                    </p>
                  )}
                {check.split_analysis && (
                  <div className="split-evidence">
                    <dl>
                      <div>
                        <dt>قيمة المستند</dt>
                        <dd>{amount(check.document_value, currency)}</dd>
                      </div>
                      <div>
                        <dt>مجموع المجموعة</dt>
                        <dd>{amount(check.split_analysis.combined_total, currency)}</dd>
                      </div>
                      <div>
                        <dt>حد الموافقة</dt>
                        <dd>{amount(check.split_analysis.approval_threshold, currency)}</dd>
                      </div>
                      <div>
                        <dt>النطاق</dt>
                        <dd>
                          {check.split_analysis.document_count} مستندات /{" "}
                          {check.split_analysis.window_days} أيام
                        </dd>
                      </div>
                    </dl>
                    <small>{check.split_analysis.privacy_note}</small>
                  </div>
                )}
                {check.budget_analysis && (
                  <div className="split-evidence budget-evidence">
                    <dl>
                      <div>
                        <dt>إجمالي الميزانية</dt>
                        <dd>{amount(check.budget_analysis.budget_total, currency)}</dd>
                      </div>
                      <div>
                        <dt>الاستخدام قبل المستند</dt>
                        <dd>{amount(check.budget_analysis.exposure_before_document, currency)}</dd>
                      </div>
                      <div>
                        <dt>أثر المستند</dt>
                        <dd>{amount(check.budget_analysis.document_effect, currency)}</dd>
                      </div>
                      <div>
                        <dt>المتبقي بعده</dt>
                        <dd>{amount(check.budget_analysis.remaining_after_document, currency)}</dd>
                      </div>
                    </dl>
                    <small>{check.budget_analysis.definition}</small>
                  </div>
                )}
                {(check.comparisons?.length || 0) > 0 && (
                  <div className="source-comparisons">
                    {check.comparisons?.map((comparison, index) => (
                      <div key={`${comparison.field}:${comparison.source_value}:${index}`}>
                        <span>{comparison.label}</span>
                        <span className={`comparison-${comparison.status.toLowerCase()}`}>
                          {comparisonStatus[comparison.status]}
                        </span>
                        <small>
                          المصدر:{" "}
                          <bdi>
                            {comparisonValue(comparison.field, comparison.source_value, currency)}
                          </bdi>
                          {comparison.invoice_value !== null && (
                            <>
                              {" "}
                              · بيانات الفاتورة:{" "}
                              <bdi>
                                {comparisonValue(
                                  comparison.field,
                                  comparison.invoice_value,
                                  currency,
                                )}
                              </bdi>
                            </>
                          )}
                        </small>
                      </div>
                    ))}
                  </div>
                )}
                {(check.price_findings?.length || 0) > 0 && (
                  <div className="price-findings">
                    {check.price_findings?.map((finding) => (
                      <div
                        key={finding.position}
                        className={`finding-${finding.status.toLowerCase()}`}
                      >
                        <div className="finding-title">
                          <strong>
                            البند {finding.position}: {finding.description}
                          </strong>
                          <span>{status[finding.status].label}</span>
                        </div>
                        <p>{finding.message}</p>
                        {finding.median_unit_price !== null &&
                          finding.current_unit_price !== null && (
                            <dl className="price-evidence">
                              <div>
                                <dt>السعر الحالي</dt>
                                <dd>
                                  <bdi>{amount(finding.current_unit_price, currency)}</bdi>
                                </dd>
                              </div>
                              <div>
                                <dt>الوسيط التاريخي</dt>
                                <dd>
                                  <bdi>{amount(finding.median_unit_price, currency)}</bdi>
                                </dd>
                              </div>
                              <div>
                                <dt>حد التنبيه</dt>
                                <dd>
                                  <bdi>{amount(finding.alert_threshold, currency)}</bdi>
                                </dd>
                              </div>
                              <div>
                                <dt>الفرق عن الوسيط</dt>
                                <dd>
                                  <bdi>{finding.difference_percent}%</bdi>
                                </dd>
                              </div>
                            </dl>
                          )}
                        <small>
                          العينة: {finding.source_invoice_count} فواتير مستقلة خلال{" "}
                          {finding.lookback_days} يومًا
                          {finding.unit ? ` · الوحدة: ${finding.unit}` : " · دون وحدة مسجلة"}
                          {finding.confidence
                            ? ` · موثوقية ${finding.confidence === "HIGH" ? "مرتفعة" : "متوسطة"}`
                            : ""}
                        </small>
                      </div>
                    ))}
                    <p className="analysis-policy">
                      السعر الفعلي بعد خصم البند وقبل الضريبة. يلزم ثلاث فواتير، ويُستخدم الوسيط
                      ونطاق الربيعات مع حد ارتفاع أدنى 20%.
                    </p>
                  </div>
                )}
                {(check.regional_findings?.length || 0) > 0 && (
                  <div className="price-findings regional-findings">
                    {check.regional_findings?.map((finding) => (
                      <div
                        key={finding.position}
                        className={"finding-" + finding.status.toLowerCase()}
                      >
                        <div className="finding-title">
                          <strong>
                            البند {finding.position}: {finding.description}
                          </strong>
                          <span>{status[finding.status].label}</span>
                        </div>
                        <p>{finding.message}</p>
                        {finding.current_unit_price !== null &&
                          finding.current_region_median !== null && (
                            <dl className="price-evidence">
                              <div>
                                <dt>السعر الحالي</dt>
                                <dd>{amount(finding.current_unit_price, currency)}</dd>
                              </div>
                              <div>
                                <dt>وسيط {finding.current_region_name}</dt>
                                <dd>{amount(finding.current_region_median, currency)}</dd>
                              </div>
                              <div>
                                <dt>الفرق</dt>
                                <dd>{finding.difference_percent}%</dd>
                              </div>
                              <div>
                                <dt>فرق تكلفة الكمية</dt>
                                <dd>{amount(finding.potential_saving, currency)}</dd>
                              </div>
                            </dl>
                          )}
                        {finding.region_comparisons.length > 0 && (
                          <div className="regional-price-table">
                            {finding.region_comparisons.map((region) => (
                              <div key={region.region_code}>
                                <strong>{region.region_name}</strong>
                                <span>{amount(region.median_unit_price, currency)}</span>
                                <small>
                                  {region.invoice_count} فواتير · {region.supplier_count} موردين
                                </small>
                              </div>
                            ))}
                          </div>
                        )}
                        <small>
                          العينة: {finding.sample_count} فواتير، {finding.supplier_count} موردين،{" "}
                          {finding.region_count} مناطق خلال {finding.lookback_days} يومًا
                          {finding.confidence && (
                            <> · موثوقية {finding.confidence === "HIGH" ? "مرتفعة" : "متوسطة"}</>
                          )}
                        </small>
                      </div>
                    ))}
                    <p className="analysis-policy">
                      المقارنة من فواتير الشركة المرسلة فقط، وبنود متقاربة في الوصف والوحدة، ولا
                      تمثل سعر سوق خارجيًا.
                    </p>
                    {check.privacy_note && <p className="privacy-note">{check.privacy_note}</p>}
                  </div>
                )}
                {(check.similarity_signals?.length || 0) > 0 && (
                  <div className="similarity-evidence">
                    {check.max_similarity_percent !== null &&
                      check.max_similarity_percent !== undefined && (
                        <div className="similarity-score">
                          <span>أعلى درجة تشابه</span>
                          <strong>{check.max_similarity_percent}%</strong>
                          <div aria-hidden="true">
                            <i
                              style={{ width: `${Math.min(check.max_similarity_percent, 100)}%` }}
                            />
                          </div>
                          <small>حد التنبيه {check.similarity_threshold_percent}%</small>
                        </div>
                      )}
                    <div className="similarity-signals">
                      {check.similarity_signals?.map((signal) => (
                        <div key={signal.code}>
                          <span>{signal.label}</span>
                          <strong>
                            {signal.available ? `${signal.score_percent}%` : "غير متوفر"}
                          </strong>
                          <small>
                            {signal.summary} · وزن الإشارة {signal.weight_percent}%
                          </small>
                        </div>
                      ))}
                    </div>
                    {check.privacy_note && <p className="privacy-note">{check.privacy_note}</p>}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {!compact && (
        <p className="audit-advisory">
          هذه النتائج تساعد المراجع ولا تعتمد الفاتورة أو ترفضها تلقائيًا.
        </p>
      )}
    </section>
  );
}
