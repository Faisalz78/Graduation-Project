import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme";
import type { AuthSession } from "../types";

const roleLabels = {
  EMPLOYEE: "موظف المشتريات",
  PROJECT_MANAGER: "مدير المشروع",
  FINANCE_MANAGER: "مدير المالية",
};

export function AppHeader({
  session,
  onLogout,
}: {
  session: AuthSession;
  onLogout: () => void;
}) {
  return (
    <View style={styles.header}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="تسجيل الخروج"
        onPress={onLogout}
        style={({ pressed }) => [styles.logout, pressed && styles.pressed]}
      >
        <Text style={styles.logoutText}>خروج</Text>
      </Pressable>
      <View style={styles.identity}>
        <Text numberOfLines={1} style={styles.userName}>
          {session.user.name}
        </Text>
        <Text style={styles.role}>{roleLabels[session.user.role]}</Text>
      </View>
      <View style={styles.mark}>
        <Text style={styles.markText}>دقّق</Text>
      </View>
    </View>
  );
}

export function BottomNavigation({
  active,
  canUpload,
  onChange,
}: {
  active: "invoices" | "upload";
  canUpload: boolean;
  onChange: (screen: "invoices" | "upload") => void;
}) {
  return (
    <View style={styles.navigation}>
      <NavigationButton
        icon="＋"
        label="رفع فاتورة"
        active={active === "upload"}
        disabled={!canUpload}
        onPress={() => onChange("upload")}
      />
      <NavigationButton
        icon="▤"
        label="الفواتير"
        active={active === "invoices"}
        onPress={() => onChange("invoices")}
      />
    </View>
  );
}

function NavigationButton({
  icon,
  label,
  active,
  disabled = false,
  onPress,
}: {
  icon: string;
  label: string;
  active: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected: active, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.navItem,
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}
    >
      <Text style={[styles.navIcon, active && styles.navActive]}>{icon}</Text>
      <Text style={[styles.navLabel, active && styles.navActive]}>{label}</Text>
      {active ? <View style={styles.navIndicator} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: {
    minHeight: 76,
    paddingHorizontal: 18,
    paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  mark: {
    width: 48,
    height: 48,
    borderRadius: 15,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  markText: { color: "#fff", fontSize: 15, fontWeight: "900" },
  identity: { flex: 1, alignItems: "flex-end" },
  userName: {
    color: colors.ink,
    fontSize: 15,
    fontWeight: "900",
    textAlign: "right",
  },
  role: { color: colors.muted, fontSize: 12, marginTop: 3 },
  logout: {
    paddingHorizontal: 13,
    paddingVertical: 9,
    borderRadius: 11,
    borderWidth: 1,
    borderColor: colors.line,
  },
  logoutText: { color: colors.muted, fontWeight: "800" },
  navigation: {
    minHeight: 72,
    paddingBottom: 6,
    flexDirection: "row",
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  navItem: { flex: 1, alignItems: "center", justifyContent: "center", gap: 2 },
  navIcon: { color: colors.muted, fontSize: 23, lineHeight: 26 },
  navLabel: { color: colors.muted, fontSize: 12, fontWeight: "800" },
  navActive: { color: colors.primary },
  navIndicator: {
    position: "absolute",
    top: 0,
    width: 42,
    height: 3,
    borderRadius: 2,
    backgroundColor: colors.primary,
  },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.35 },
});
