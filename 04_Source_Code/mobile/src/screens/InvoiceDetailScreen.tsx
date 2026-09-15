import { useCallback, useEffect, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError, request } from "../api";
import { ErrorState, LoadingState } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { colors, commonStyles } from "../theme";
import type { AuditCheck, Invoice } from "../types";

const eventLabels: Record<string, string> = {
  DRAFT_CREATED: "إنشاء المسودة",
  FILE_ATTACHED: "حفظ الملف الأصلي",
  DRAFT_UPDATED: "تعديل بيانات الفاتورة",
  EXTRACTION_REQUESTED: "طلب قراءة المستند",
  EXTRACTION_REVIEWED: "مراجعة البيانات المستخرجة",
  INVOICE_SUBMITTED: "إرسال الفاتورة",
  INVOICE_RESUBMITTED: "إعادة إرسال الفاتورة",
  PROJECT_APPROVED: "موافقة مدير المشروع",
  FINANCE_APPROVED: "اعتماد المالية",
  CHANGES_REQUESTED: "طلب تعديل",
  INVOICE_REJECTED: "رفض الفاتورة",
};

function dateLabel(value: string) {
  return new Date(value).toLocaleDateString("ar-SA", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function InvoiceDetailScreen({
  invoiceId,
  token,
  onBack,
  onExpired,
}: {
  invoiceId: string;
  token: string;
  onBack: () => void;
  onExpired: () => void;
}) {
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setInvoice(await request<Invoice>(`/invoices/${invoiceId}`, token));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onExpired();
      else
        setError(
          reason instanceof ApiError ? reason.message : "تعذر تحميل الفاتورة.",
        );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [invoiceId, onExpired, token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingState label="جارٍ تحميل تفاصيل الفاتورة…" />;
  if (error || !invoice) {
    return (
      <View style={commonStyles.screen}>
        <Pressable onPress={onBack} style={styles.backOuter}>
          <Text style={styles.backText}>→ العودة للفواتير</Text>
        </Pressable>
        <ErrorState
          message={error || "الفاتورة غير متاحة."}
          onRetry={() => void load()}
        />
      </View>
    );
  }

  const warningChecks =
    invoice.audit?.checks.filter((check) => check.status === "WARNING") || [];
  const checkedChecks =
    invoice.audit?.checks.filter((check) => check.status === "PASS") || [];

  return (
    <ScrollView
      contentContainerStyle={commonStyles.content}
      refreshControl={
        <RefreshControl
          colors={[colors.primary]}
          onRefresh={() => {
            setRefreshing(true);
            void load();
          }}
          refreshing={refreshing}
          tintColor={colors.primary}
        />
      }
      style={commonStyles.screen}
    >
      <Pressable
        accessibilityRole="button"
        onPress={onBack}
        style={styles.back}
      >
        <Text style={styles.backText}>→ العودة للفواتير</Text>
      </Pressable>

      <View style={styles.titleRow}>
        <StatusBadge status={invoice.status} />
        <View style={styles.titleCopy}>
          <Text style={commonStyles.title}>
            {invoice.invoice_number || "فاتورة بلا رقم"}
          </Text>
          <Text style={commonStyles.subtitle}>
            النسخة {invoice.revision} · {dateLabel(invoice.created_at)}
          </Text>
        </View>
      </View>

      <View style={[commonStyles.card, styles.summary]}>
        <InfoRow
          label="المشروع"
          value={`${invoice.project.code} · ${invoice.project.name}`}
        />
        <InfoRow
          label="المورد"
          value={invoice.supplier?.name || "لم يحدد بعد"}
        />
        <InfoRow
          label="تاريخ الفاتورة"
          value={invoice.invoice_date || "لم يحدد بعد"}
        />
        <InfoRow label="الملف الأصلي" value={invoice.attachment.name} />
        <InfoRow
          label="الإجمالي"
          value={
            invoice.totals
              ? `${invoice.totals.grand_total} ${invoice.currency}`
              : "البيانات غير مكتملة"
          }
          strong
        />
      </View>

      {invoice.note ? (
        <View style={commonStyles.card}>
          <Text style={styles.sectionTitle}>ملاحظة الموظف</Text>
          <Text style={styles.bodyText}>{invoice.note}</Text>
        </View>
      ) : null}

      {invoice.audit?.risk ? (
        <View style={[commonStyles.card, styles.riskCard]}>
          <View style={styles.riskTop}>
            <View style={styles.scoreCircle}>
              <Text style={styles.score}>{invoice.audit.risk.score}</Text>
              <Text style={styles.scoreOut}>/100</Text>
            </View>
            <View style={styles.riskCopy}>
              <Text style={styles.sectionTitle}>أولوية المراجعة</Text>
              <Text style={styles.bodyText}>{invoice.audit.risk.advisory}</Text>
            </View>
          </View>
          <Text style={styles.coverage}>
            تم تقييم {invoice.audit.risk.evaluated_count} من{" "}
            {invoice.audit.risk.total_checks} فحصًا · الثقة{" "}
            {confidenceLabel(invoice.audit.risk.confidence)}
          </Text>
        </View>
      ) : (
        <View style={[commonStyles.card, styles.pendingCard]}>
          <Text style={styles.sectionTitle}>التدقيق الآلي</Text>
          <Text style={styles.bodyText}>
            تظهر نتيجة التدقيق ودرجة الأولوية بعد إرسال الفاتورة للمراجعة.
          </Text>
        </View>
      )}

      {warningChecks.length ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            تنبيهات تحتاج مراجعة ({warningChecks.length})
          </Text>
          {warningChecks.map((check) => (
            <CheckCard check={check} key={check.code} />
          ))}
        </View>
      ) : null}

      {checkedChecks.length ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            فحوص ناجحة ({checkedChecks.length})
          </Text>
          {checkedChecks.map((check) => (
            <CheckCard check={check} key={check.code} />
          ))}
        </View>
      ) : null}

      {invoice.events?.length ? (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>سجل الإجراءات</Text>
          <View style={commonStyles.card}>
            {invoice.events.map((event, index) => (
              <View key={event.id} style={styles.eventRow}>
                <View style={styles.eventContent}>
                  <Text style={styles.eventTitle}>
                    {eventLabels[event.action] || event.action}
                  </Text>
                  <Text style={styles.eventMeta}>
                    {event.actor_name} · {dateLabel(event.created_at)}
                  </Text>
                </View>
                <View style={styles.timeline}>
                  <View style={styles.dot} />
                  {index < (invoice.events?.length || 0) - 1 ? (
                    <View style={styles.line} />
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

function InfoRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <View style={styles.infoRow}>
      <Text style={[styles.infoValue, strong && styles.infoStrong]}>
        {value}
      </Text>
      <Text style={styles.infoLabel}>{label}</Text>
    </View>
  );
}

function CheckCard({ check }: { check: AuditCheck }) {
  const warning = check.status === "WARNING";
  return (
    <View
      style={[styles.check, warning ? styles.checkWarning : styles.checkPass]}
    >
      <Text
        style={[
          styles.checkSymbol,
          warning ? styles.warningText : styles.passText,
        ]}
      >
        {warning ? "!" : "✓"}
      </Text>
      <View style={styles.checkCopy}>
        <Text style={styles.checkTitle}>{check.label}</Text>
        <Text style={styles.checkMessage}>{check.message}</Text>
      </View>
    </View>
  );
}

function confidenceLabel(value: "LOW" | "MEDIUM" | "HIGH") {
  return { LOW: "منخفضة", MEDIUM: "متوسطة", HIGH: "مرتفعة" }[value];
}

const styles = StyleSheet.create({
  backOuter: { padding: 18 },
  back: { alignSelf: "flex-end", paddingVertical: 5 },
  backText: { color: colors.primary, fontSize: 14, fontWeight: "900" },
  titleRow: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  titleCopy: { flex: 1, alignItems: "flex-end" },
  summary: { gap: 0 },
  infoRow: {
    minHeight: 49,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#edf1ef",
  },
  infoLabel: { color: colors.muted, fontSize: 12, textAlign: "right" },
  infoValue: {
    flex: 1,
    color: colors.ink,
    fontSize: 14,
    fontWeight: "700",
    textAlign: "left",
  },
  infoStrong: { color: colors.primaryDark, fontSize: 16, fontWeight: "900" },
  section: { gap: 9 },
  sectionTitle: {
    color: colors.ink,
    fontSize: 16,
    fontWeight: "900",
    textAlign: "right",
  },
  bodyText: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 22,
    marginTop: 7,
    textAlign: "right",
    writingDirection: "rtl",
  },
  riskCard: { borderColor: "#e3c686", backgroundColor: "#fffaf0", gap: 12 },
  riskTop: { flexDirection: "row", alignItems: "center", gap: 14 },
  riskCopy: { flex: 1, alignItems: "flex-end" },
  scoreCircle: {
    width: 74,
    height: 74,
    borderRadius: 37,
    backgroundColor: colors.warningSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  score: { color: colors.warning, fontSize: 24, fontWeight: "900" },
  scoreOut: { color: colors.warning, fontSize: 10, fontWeight: "800" },
  coverage: {
    color: colors.warning,
    fontSize: 12,
    textAlign: "right",
    writingDirection: "rtl",
  },
  pendingCard: { backgroundColor: colors.infoSoft, borderColor: "#c8e1ea" },
  check: {
    flexDirection: "row",
    gap: 11,
    borderRadius: 14,
    borderWidth: 1,
    padding: 13,
  },
  checkWarning: { backgroundColor: colors.warningSoft, borderColor: "#eed8a8" },
  checkPass: { backgroundColor: colors.primarySoft, borderColor: "#c6e0d7" },
  checkSymbol: {
    width: 23,
    fontSize: 18,
    fontWeight: "900",
    textAlign: "center",
  },
  warningText: { color: colors.warning },
  passText: { color: colors.primary },
  checkCopy: { flex: 1, alignItems: "flex-end" },
  checkTitle: {
    color: colors.ink,
    fontSize: 13,
    fontWeight: "900",
    textAlign: "right",
  },
  checkMessage: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 19,
    marginTop: 4,
    textAlign: "right",
    writingDirection: "rtl",
  },
  eventRow: { flexDirection: "row", minHeight: 62 },
  eventContent: { flex: 1, alignItems: "flex-end", paddingBottom: 14 },
  eventTitle: { color: colors.ink, fontSize: 13, fontWeight: "900" },
  eventMeta: {
    color: colors.muted,
    fontSize: 11,
    marginTop: 4,
    textAlign: "right",
  },
  timeline: { width: 24, alignItems: "center" },
  dot: {
    width: 11,
    height: 11,
    borderRadius: 6,
    backgroundColor: colors.primary,
    marginTop: 3,
  },
  line: { width: 2, flex: 1, backgroundColor: colors.line, marginVertical: 3 },
});
