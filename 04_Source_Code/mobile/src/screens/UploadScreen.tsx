import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as DocumentPicker from "expo-document-picker";

import { ApiError, request } from "../api";
import { ErrorState, LoadingState } from "../components/Feedback";
import { colors, commonStyles } from "../theme";
import type { Invoice, Project, UserRole } from "../types";

const MAX_BYTES = 10 * 1024 * 1024;

export function UploadScreen({
  token,
  role,
  onUploaded,
  onExpired,
}: {
  token: string;
  role: UserRole;
  onUploaded: (invoiceId: string) => void;
  onExpired: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [asset, setAsset] = useState<DocumentPicker.DocumentPickerAsset | null>(
    null,
  );
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const requestIdentity = useRef<{ signature: string; key: string } | null>(
    null,
  );

  const loadProjects = useCallback(async () => {
    setError("");
    try {
      const data = await request<Project[]>("/projects", token);
      setProjects(data);
      if (data.length === 1) setProjectId(data[0].id);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onExpired();
      else
        setError(
          reason instanceof ApiError ? reason.message : "تعذر تحميل المشاريع.",
        );
    } finally {
      setLoading(false);
    }
  }, [onExpired, token]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  async function chooseDocument() {
    const result = await DocumentPicker.getDocumentAsync({
      type: [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "application/xml",
        "text/xml",
      ],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled) return;
    const selected = result.assets[0];
    if (selected.size && selected.size > MAX_BYTES) {
      setAsset(null);
      setError("حجم الملف يتجاوز 10 ميغابايت.");
      return;
    }
    setError("");
    setAsset(selected);
  }

  async function upload() {
    if (!projectId) {
      setError("اختر المشروع المرتبط بالفاتورة.");
      return;
    }
    if (!asset) {
      setError("اختر ملف الفاتورة أولًا.");
      return;
    }

    setSubmitting(true);
    setError("");
    const signature = `${projectId}|${asset.uri}|${note.trim()}`;
    if (requestIdentity.current?.signature !== signature) {
      requestIdentity.current = {
        signature,
        key: `mobile_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
      };
    }

    const form = new FormData();
    form.append("project_id", projectId);
    form.append("note", note.trim());
    form.append("file", {
      uri: asset.uri,
      name: asset.name,
      type: asset.mimeType || "application/octet-stream",
    } as unknown as Blob);

    try {
      const invoice = await request<Invoice>("/invoices", token, {
        method: "POST",
        body: form,
        headers: { "Idempotency-Key": requestIdentity.current.key },
      });
      requestIdentity.current = null;
      onUploaded(invoice.id);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onExpired();
      else
        setError(
          reason instanceof ApiError ? reason.message : "تعذر رفع الفاتورة.",
        );
    } finally {
      setSubmitting(false);
    }
  }

  if (role !== "EMPLOYEE") {
    return (
      <View style={styles.roleNotice}>
        <Text style={styles.roleIcon}>✓</Text>
        <Text style={styles.roleTitle}>الرفع مخصص للموظف</Text>
        <Text style={commonStyles.subtitle}>
          حساب المدير يراجع الفواتير من القائمة. إنشاء المسودات متاح لموظف
          المشتريات فقط.
        </Text>
      </View>
    );
  }
  if (loading) return <LoadingState label="جارٍ تحميل مشاريعك…" />;
  if (error && !projects.length) {
    return <ErrorState message={error} onRetry={() => void loadProjects()} />;
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={commonStyles.screen}
    >
      <ScrollView
        contentContainerStyle={commonStyles.content}
        keyboardShouldPersistTaps="handled"
      >
        <View>
          <Text style={commonStyles.title}>رفع فاتورة</Text>
          <Text style={commonStyles.subtitle}>
            أنشئ مسودة خاصة. راجع بياناتها في المنصة قبل إرسالها إلى المدير.
          </Text>
        </View>

        <View style={[commonStyles.card, styles.form]}>
          <View style={styles.field}>
            <Text style={commonStyles.label}>1. اختر المشروع</Text>
            <View style={styles.projectList}>
              {projects.map((project) => (
                <Pressable
                  key={project.id}
                  onPress={() => setProjectId(project.id)}
                  style={[
                    styles.project,
                    projectId === project.id && styles.projectSelected,
                  ]}
                >
                  <View style={styles.projectCode}>
                    <Text style={styles.projectCodeText}>{project.code}</Text>
                  </View>
                  <Text style={styles.projectName}>{project.name}</Text>
                  <View style={styles.radio}>
                    {projectId === project.id ? (
                      <View style={styles.radioDot} />
                    ) : null}
                  </View>
                </Pressable>
              ))}
            </View>
          </View>

          <View style={styles.field}>
            <Text style={commonStyles.label}>2. اختر ملف الفاتورة</Text>
            <Pressable onPress={chooseDocument} style={styles.picker}>
              <Text style={styles.pickerIcon}>{asset ? "✓" : "↑"}</Text>
              <View style={styles.pickerCopy}>
                <Text numberOfLines={1} style={styles.pickerTitle}>
                  {asset ? asset.name : "اختيار PDF أو صورة أو XML"}
                </Text>
                <Text style={styles.pickerMeta}>
                  {asset
                    ? asset.size
                      ? `${(asset.size / 1024 / 1024).toFixed(2)} ميغابايت`
                      : "الملف جاهز للرفع"
                    : "الحد الأقصى 10 ميغابايت"}
                </Text>
              </View>
            </Pressable>
          </View>

          <View style={styles.field}>
            <Text style={commonStyles.label}>3. ملاحظة اختيارية</Text>
            <TextInput
              editable={!submitting}
              maxLength={1000}
              multiline
              onChangeText={setNote}
              placeholder="مثال: فاتورة توريد مواد للموقع"
              placeholderTextColor="#91a19b"
              style={[commonStyles.input, styles.note]}
              textAlignVertical="top"
              value={note}
            />
            <Text style={styles.counter}>{note.length}/1000</Text>
          </View>

          {error ? (
            <View accessibilityRole="alert" style={commonStyles.errorBox}>
              <Text style={commonStyles.errorText}>{error}</Text>
            </View>
          ) : null}

          <Pressable
            disabled={submitting}
            onPress={upload}
            style={({ pressed }) => [
              commonStyles.primaryButton,
              (pressed || submitting) && styles.pressed,
            ]}
          >
            {submitting ? (
              <View style={styles.progress}>
                <ActivityIndicator color="#fff" />
                <Text style={commonStyles.primaryButtonText}>جارٍ الرفع…</Text>
              </View>
            ) : (
              <Text style={commonStyles.primaryButtonText}>إنشاء المسودة</Text>
            )}
          </Pressable>
        </View>

        <View style={styles.safety}>
          <Text style={styles.safetyTitle}>المسودة خاصة</Text>
          <Text style={styles.safetyText}>
            لن تظهر للمراجعين حتى تكمل البيانات وتؤكد إرسالها من منصة الويب.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  form: { gap: 20 },
  field: { gap: 9 },
  projectList: { gap: 8 },
  project: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 13,
    padding: 10,
  },
  projectSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  projectCode: {
    minWidth: 38,
    height: 34,
    borderRadius: 9,
    backgroundColor: "#edf2f0",
    alignItems: "center",
    justifyContent: "center",
  },
  projectCodeText: {
    color: colors.primaryDark,
    fontSize: 11,
    fontWeight: "900",
  },
  projectName: {
    flex: 1,
    color: colors.ink,
    fontSize: 14,
    fontWeight: "800",
    textAlign: "right",
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  radioDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.primary,
  },
  picker: {
    minHeight: 96,
    borderRadius: 15,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.primary,
    backgroundColor: "#f7fbf9",
    flexDirection: "row",
    alignItems: "center",
    gap: 13,
    padding: 14,
  },
  pickerIcon: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: colors.primarySoft,
    color: colors.primary,
    fontSize: 25,
    fontWeight: "900",
    textAlign: "center",
    lineHeight: 42,
  },
  pickerCopy: { flex: 1, alignItems: "flex-end", gap: 5 },
  pickerTitle: {
    color: colors.ink,
    fontSize: 14,
    fontWeight: "900",
    textAlign: "right",
  },
  pickerMeta: { color: colors.muted, fontSize: 12 },
  note: { minHeight: 96, paddingTop: 13 },
  counter: { color: colors.muted, fontSize: 11, textAlign: "left" },
  progress: { flexDirection: "row", alignItems: "center", gap: 10 },
  safety: {
    backgroundColor: colors.infoSoft,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#c8e1ea",
    padding: 14,
  },
  safetyTitle: {
    color: colors.info,
    fontSize: 13,
    fontWeight: "900",
    textAlign: "right",
  },
  safetyText: {
    color: colors.info,
    fontSize: 12,
    lineHeight: 20,
    marginTop: 4,
    textAlign: "right",
    writingDirection: "rtl",
  },
  roleNotice: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    padding: 30,
  },
  roleIcon: {
    width: 62,
    height: 62,
    borderRadius: 31,
    color: colors.primary,
    backgroundColor: colors.primarySoft,
    fontSize: 30,
    fontWeight: "900",
    lineHeight: 60,
    textAlign: "center",
  },
  roleTitle: { color: colors.ink, fontSize: 19, fontWeight: "900" },
  pressed: { opacity: 0.7 },
});
