import { StyleSheet, Text, View } from "react-native";

import { colors } from "../theme";
import type { InvoiceStatus } from "../types";

export const statusLabels: Record<InvoiceStatus, string> = {
  DRAFT: "مسودة خاصة",
  PROJECT_REVIEW: "مراجعة مدير المشروع",
  FINANCE_REVIEW: "مراجعة المالية",
  CHANGES_REQUESTED: "مطلوب تعديل",
  APPROVED: "معتمدة",
  REJECTED: "مرفوضة",
};

const tones: Record<InvoiceStatus, { backgroundColor: string; color: string }> =
  {
    DRAFT: { backgroundColor: "#edf1ef", color: "#52635d" },
    PROJECT_REVIEW: { backgroundColor: colors.infoSoft, color: colors.info },
    FINANCE_REVIEW: { backgroundColor: "#eee9fa", color: "#60428c" },
    CHANGES_REQUESTED: {
      backgroundColor: colors.warningSoft,
      color: colors.warning,
    },
    APPROVED: {
      backgroundColor: colors.primarySoft,
      color: colors.primaryDark,
    },
    REJECTED: { backgroundColor: colors.dangerSoft, color: colors.danger },
  };

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const tone = tones[status];
  return (
    <View style={[styles.badge, { backgroundColor: tone.backgroundColor }]}>
      <Text style={[styles.text, { color: tone.color }]}>
        {statusLabels[status]}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: "flex-end",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  text: { fontSize: 12, fontWeight: "900" },
});
