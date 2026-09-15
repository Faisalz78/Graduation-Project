import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

import type { MobileLoginResult } from "./types";

const DEFAULT_API_URL =
  Platform.OS === "android"
    ? "http://10.0.2.2:8000/api/v1"
    : "http://127.0.0.1:8000/api/v1";

export const API_URL = (
  process.env.EXPO_PUBLIC_API_URL || DEFAULT_API_URL
).replace(/\/$/, "");
const TOKEN_KEY = "invoice-audit-session";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function messageFromDetail(detail: unknown) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "راجع البيانات المختارة ثم حاول مجددًا.";
  return "تعذر إكمال الطلب. حاول مجددًا.";
}

export async function request<T = unknown>(
  path: string,
  token?: string | null,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, "تعذر الاتصال بالخادم. تحقق من العنوان والشبكة.");
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, messageFromDetail(data.detail));
  }
  return data as T;
}

export function login(email: string, password: string) {
  return request<MobileLoginResult>("/auth/mobile/login", null, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function storeToken(token: string) {
  if (Platform.OS === "web") {
    globalThis.sessionStorage?.setItem(TOKEN_KEY, token);
    return Promise.resolve();
  }
  return SecureStore.setItemAsync(TOKEN_KEY, token);
}

export function getToken() {
  if (Platform.OS === "web") {
    return Promise.resolve(
      globalThis.sessionStorage?.getItem(TOKEN_KEY) || null,
    );
  }
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export function clearToken() {
  if (Platform.OS === "web") {
    globalThis.sessionStorage?.removeItem(TOKEN_KEY);
    return Promise.resolve();
  }
  return SecureStore.deleteItemAsync(TOKEN_KEY);
}
