import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors, commonStyles } from "../theme";

export function LoadingState({
  label = "جارٍ تحميل البيانات…",
}: {
  label?: string;
}) {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={colors.primary} />
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <View style={styles.center}>
      <View style={commonStyles.errorBox}>
        <Text style={commonStyles.errorText}>{message}</Text>
      </View>
      <Pressable onPress={onRetry} style={styles.retry}>
        <Text style={styles.retryText}>إعادة المحاولة</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
    padding: 24,
  },
  muted: { color: colors.muted, fontSize: 14 },
  retry: {
    paddingHorizontal: 18,
    paddingVertical: 11,
    borderRadius: 12,
    backgroundColor: colors.primarySoft,
  },
  retryText: { color: colors.primaryDark, fontWeight: "900" },
});
