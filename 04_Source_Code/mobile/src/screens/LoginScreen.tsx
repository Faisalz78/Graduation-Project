import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";

import { ApiError, login } from "../api";
import { colors, commonStyles } from "../theme";
import type { MobileLoginResult } from "../types";

export function LoginScreen({
  onLogin,
}: {
  onLogin: (result: MobileLoginResult) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!email.trim() || !password) {
      setError("أدخل البريد الإلكتروني وكلمة المرور.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      onLogin(await login(email.trim(), password));
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "تعذر تسجيل الدخول.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.screen}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.brand}>
            <View style={styles.mark}>
              <Text style={styles.markText}>دقّق</Text>
            </View>
            <Text style={styles.eyebrow}>منصة تدقيق الفواتير</Text>
            <Text style={styles.title}>تابع فواتير مشروعك من جوالك</Text>
            <Text style={styles.subtitle}>
              ارفع المستندات بأمان، راقب حالة المراجعة، واطلع على التنبيهات
              وأسبابها.
            </Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.formTitle}>تسجيل الدخول</Text>
            <View style={styles.field}>
              <Text style={commonStyles.label}>البريد الإلكتروني</Text>
              <TextInput
                autoCapitalize="none"
                autoComplete="email"
                editable={!submitting}
                keyboardType="email-address"
                onChangeText={setEmail}
                placeholder="name@company.com"
                placeholderTextColor="#91a19b"
                returnKeyType="next"
                style={commonStyles.input}
                value={email}
              />
            </View>
            <View style={styles.field}>
              <Text style={commonStyles.label}>كلمة المرور</Text>
              <View>
                <TextInput
                  autoCapitalize="none"
                  autoComplete="current-password"
                  editable={!submitting}
                  onChangeText={setPassword}
                  onSubmitEditing={submit}
                  placeholder="••••••••"
                  placeholderTextColor="#91a19b"
                  returnKeyType="done"
                  secureTextEntry={!showPassword}
                  style={[commonStyles.input, styles.passwordInput]}
                  value={password}
                />
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setShowPassword((visible) => !visible)}
                  style={styles.showPassword}
                >
                  <Text style={styles.showPasswordText}>
                    {showPassword ? "إخفاء" : "إظهار"}
                  </Text>
                </Pressable>
              </View>
            </View>
            {error ? (
              <View accessibilityRole="alert" style={commonStyles.errorBox}>
                <Text style={commonStyles.errorText}>{error}</Text>
              </View>
            ) : null}
            <Pressable
              accessibilityRole="button"
              disabled={submitting}
              onPress={submit}
              style={({ pressed }) => [
                commonStyles.primaryButton,
                (pressed || submitting) && styles.pressed,
              ]}
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={commonStyles.primaryButtonText}>دخول آمن</Text>
              )}
            </Pressable>
          </View>
          <Text style={styles.privacy}>
            بيانات الدخول محفوظة في التخزين الآمن للجهاز.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.canvas },
  content: { flexGrow: 1, justifyContent: "center", padding: 22, gap: 22 },
  brand: { alignItems: "flex-end", gap: 9 },
  mark: {
    width: 72,
    height: 72,
    borderRadius: 22,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
  },
  markText: { color: "#fff", fontSize: 21, fontWeight: "900" },
  eyebrow: { color: colors.primary, fontSize: 13, fontWeight: "900" },
  title: {
    color: colors.ink,
    fontSize: 28,
    lineHeight: 38,
    fontWeight: "900",
    textAlign: "right",
    writingDirection: "rtl",
  },
  subtitle: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 24,
    textAlign: "right",
    writingDirection: "rtl",
  },
  form: {
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    padding: 18,
    gap: 16,
  },
  formTitle: {
    color: colors.ink,
    fontSize: 20,
    fontWeight: "900",
    textAlign: "right",
  },
  field: { gap: 7 },
  passwordInput: { paddingLeft: 72 },
  showPassword: { position: "absolute", left: 8, top: 7, padding: 10 },
  showPasswordText: { color: colors.primary, fontSize: 13, fontWeight: "900" },
  privacy: { color: colors.muted, fontSize: 12, textAlign: "center" },
  pressed: { opacity: 0.7 },
});
