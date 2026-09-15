import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
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
import type { Invoice, InvoicePage, InvoiceStatus } from "../types";

const filters: { value: InvoiceStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "الكل" },
  { value: "DRAFT", label: "المسودات" },
  { value: "PROJECT_REVIEW", label: "مراجعة المشروع" },
  { value: "FINANCE_REVIEW", label: "مراجعة المالية" },
  { value: "CHANGES_REQUESTED", label: "مطلوب تعديل" },
  { value: "APPROVED", label: "المعتمدة" },
  { value: "REJECTED", label: "المرفوضة" },
];

export function InvoiceListScreen({
  token,
  onExpired,
  onOpenInvoice,
}: {
  token: string;
  onExpired: () => void;
  onOpenInvoice: (invoiceId: string) => void;
}) {
  const [status, setStatus] = useState<InvoiceStatus | "ALL">("ALL");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (targetPage = 1, append = false) => {
      append ? setLoadingMore(true) : setLoading(true);
      setError("");
      try {
        const query = status === "ALL" ? "" : `&status=${status}`;
        const data = await request<InvoicePage>(
          `/invoices?page=${targetPage}&page_size=20${query}`,
          token,
        );
        setInvoices((current) =>
          append ? [...current, ...data.items] : data.items,
        );
        setTotal(data.total);
        setPage(data.page);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 401) onExpired();
        else
          setError(
            reason instanceof ApiError
              ? reason.message
              : "تعذر تحميل الفواتير.",
          );
      } finally {
        setLoading(false);
        setLoadingMore(false);
        setRefreshing(false);
      }
    },
    [onExpired, status, token],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !invoices.length) return <LoadingState />;
  if (error && !invoices.length)
    return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <View style={commonStyles.screen}>
      <FlatList
        contentContainerStyle={styles.list}
        data={invoices}
        keyExtractor={(invoice) => invoice.id}
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
        ListHeaderComponent={
          <View style={styles.headerBlock}>
            <View>
              <Text style={commonStyles.title}>الفواتير</Text>
              <Text style={commonStyles.subtitle}>
                {total
                  ? `${total} مستندًا ضمن صلاحياتك`
                  : "المستندات التي يحق لك الوصول إليها"}
              </Text>
            </View>
            <ScrollView
              contentContainerStyle={styles.filters}
              horizontal
              showsHorizontalScrollIndicator={false}
            >
              {filters.map((filter) => (
                <Pressable
                  key={filter.value}
                  onPress={() => {
                    setInvoices([]);
                    setStatus(filter.value);
                  }}
                  style={[
                    styles.filter,
                    status === filter.value && styles.filterActive,
                  ]}
                >
                  <Text
                    style={[
                      styles.filterText,
                      status === filter.value && styles.filterTextActive,
                    ]}
                  >
                    {filter.label}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
            {error ? (
              <View style={commonStyles.errorBox}>
                <Text style={commonStyles.errorText}>{error}</Text>
              </View>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>▤</Text>
            <Text style={styles.emptyTitle}>لا توجد فواتير هنا</Text>
            <Text style={styles.emptyText}>
              غيّر التصفية أو ارفع أول فاتورة من تبويب الرفع.
            </Text>
          </View>
        }
        ListFooterComponent={
          invoices.length < total ? (
            <Pressable
              disabled={loadingMore}
              onPress={() => void load(page + 1, true)}
              style={styles.more}
            >
              {loadingMore ? (
                <ActivityIndicator color={colors.primary} />
              ) : (
                <Text style={styles.moreText}>عرض المزيد</Text>
              )}
            </Pressable>
          ) : null
        }
        renderItem={({ item }) => (
          <InvoiceCard invoice={item} onPress={() => onOpenInvoice(item.id)} />
        )}
      />
    </View>
  );
}

function InvoiceCard({
  invoice,
  onPress,
}: {
  invoice: Invoice;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        commonStyles.card,
        styles.card,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.cardTop}>
        <StatusBadge status={invoice.status} />
        <View style={styles.cardIdentity}>
          <Text numberOfLines={1} style={styles.invoiceNumber}>
            {invoice.invoice_number || "فاتورة بلا رقم"}
          </Text>
          <Text numberOfLines={1} style={styles.supplier}>
            {invoice.supplier?.name || invoice.attachment.name}
          </Text>
        </View>
      </View>
      <View style={styles.rule} />
      <View style={styles.cardBottom}>
        <View style={styles.amountBlock}>
          <Text style={styles.metaLabel}>الإجمالي</Text>
          <Text style={styles.amount}>
            {invoice.totals
              ? `${invoice.totals.grand_total} ${invoice.currency}`
              : "غير مكتمل"}
          </Text>
        </View>
        <View style={styles.projectBlock}>
          <Text style={styles.metaLabel}>المشروع</Text>
          <Text numberOfLines={1} style={styles.metaValue}>
            {invoice.project.code} · {invoice.project.name}
          </Text>
        </View>
      </View>
      {invoice.audit?.risk ? (
        <View style={styles.riskLine}>
          <Text style={styles.riskValue}>{invoice.audit.risk.score}/100</Text>
          <Text style={styles.riskLabel}>درجة أولوية المراجعة</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { padding: 18, paddingBottom: 36, gap: 12 },
  headerBlock: { gap: 14, marginBottom: 4 },
  filters: { flexDirection: "row-reverse", gap: 8 },
  filter: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    paddingHorizontal: 13,
    paddingVertical: 9,
  },
  filterActive: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  filterText: { color: colors.muted, fontSize: 12, fontWeight: "800" },
  filterTextActive: { color: "#fff" },
  card: { gap: 12 },
  cardTop: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  cardIdentity: { flex: 1, alignItems: "flex-end", gap: 4 },
  invoiceNumber: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: "900",
    textAlign: "right",
  },
  supplier: { color: colors.muted, fontSize: 13, textAlign: "right" },
  rule: { height: 1, backgroundColor: colors.line },
  cardBottom: { flexDirection: "row", gap: 12 },
  amountBlock: { minWidth: 100, alignItems: "flex-start" },
  projectBlock: { flex: 1, alignItems: "flex-end" },
  metaLabel: { color: colors.muted, fontSize: 11, marginBottom: 3 },
  metaValue: {
    color: colors.ink,
    fontSize: 13,
    fontWeight: "800",
    textAlign: "right",
  },
  amount: { color: colors.ink, fontSize: 14, fontWeight: "900" },
  riskLine: {
    flexDirection: "row",
    justifyContent: "space-between",
    backgroundColor: colors.warningSoft,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: 11,
  },
  riskLabel: { color: colors.warning, fontSize: 12, fontWeight: "800" },
  riskValue: { color: colors.warning, fontSize: 12, fontWeight: "900" },
  empty: {
    alignItems: "center",
    paddingVertical: 54,
    paddingHorizontal: 20,
    gap: 8,
  },
  emptyIcon: { color: "#9baca6", fontSize: 38 },
  emptyTitle: { color: colors.ink, fontSize: 18, fontWeight: "900" },
  emptyText: { color: colors.muted, lineHeight: 22, textAlign: "center" },
  more: { alignItems: "center", padding: 15 },
  moreText: { color: colors.primary, fontWeight: "900" },
  pressed: { opacity: 0.72, transform: [{ scale: 0.995 }] },
});
