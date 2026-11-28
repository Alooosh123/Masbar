import type {
  AssistantResponse,
  AuditEntry,
  ChatRequest,
  ChatResponse,
  ComponentSummary,
  EquipmentSummary,
  HealthResponse,
  AuthMeResponse,
  AuthUser,
  ConversationSummary,
  ConversationDetail,
} from "../types";

function inferApiUrl(): string {
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  if (configured && configured.trim()) return configured.trim().replace(/\/$/, "");

  if (typeof window !== "undefined") {
    // Vite development server runs separately from the local API.
    if (import.meta.env.DEV && window.location.hostname) {
      return `http://${window.location.hostname}:8010`;
    }

    // Production frontend proxies /api, /health and /ws to the private backend.
    return window.location.origin;
  }

  return "http://localhost:8010";
}

export const API_URL = inferApiUrl();

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 60_000);
  try {
    response = await fetch(`${API_URL}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "استغرق الخادم وقتًا أطول من المتوقع. تحقق من اتصال الخدمة ثم أعد المحاولة.",
        408,
        "request_timeout"
      );
    }
    throw new ApiError(
      "تعذر الاتصال بالخادم. تحقق من تشغيل الخادم الخلفي واتصال الواجهة به.",
      0,
      "network_error"
    );
  } finally {
    window.clearTimeout(timeoutId);
  }

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message_ar || "حدث خطأ غير متوقع في الخادم.";
    throw new ApiError(message, response.status, detail?.code);
  }
  return payload as T;
}

export interface IdentifyPayload {
  part_number?: string;
  transcript?: string;
  image_base64?: string;
  visual_confidence?: number;
  bounding_box?: [number, number, number, number];
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  me: () => request<AuthMeResponse>("/api/v1/auth/me"),

  login: (email: string, password: string) =>
    request<{ authenticated: boolean; user: AuthUser }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  googleLogin: (credential: string) => request<{ authenticated: boolean; user: AuthUser }>("/api/v1/auth/google", { method: "POST", body: JSON.stringify({ credential }) }),\n\n  logout: () => request<{ authenticated: boolean }>("/api/v1/auth/logout", { method: "POST" }),

  customers: () => request<{ customers: AuthUser[] }>("/api/v1/auth/users/customers"),

  createCustomer: (email: string, displayName: string) =>
    request<{ user: AuthUser; temporary_password: string; must_change_password: boolean }>(
      "/api/v1/auth/users/customers",
      { method: "POST", body: JSON.stringify({ email, display_name: displayName }) }
    ),

  updateCustomer: (id: string, payload: { email?: string; display_name?: string }) =>
    request<{ user: AuthUser }>(`/api/v1/auth/users/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  setCustomerActive: (id: string, isActive: boolean) =>
    request<{ user: AuthUser }>(`/api/v1/auth/users/${encodeURIComponent(id)}/activation`, {
      method: "POST",
      body: JSON.stringify({ is_active: isActive }),
    }),

  resetCustomerPassword: (id: string) =>
    request<{ user: AuthUser; temporary_password: string; must_change_password: boolean }>(
      `/api/v1/auth/users/${encodeURIComponent(id)}/reset-password`,
      { method: "POST" }
    ),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ changed: boolean; user: AuthUser }>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  conversations: () =>
    request<{ conversations: ConversationSummary[] }>("/api/v1/conversations"),

  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/v1/conversations/${encodeURIComponent(id)}`),

  deleteConversation: (id: string) =>
    request<{ deleted: boolean; conversation_id: string }>(
      `/api/v1/conversations/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),

  chat: (payload: ChatRequest) =>
    request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  equipment: () => request<EquipmentSummary[]>("/api/v1/equipment"),

  components: (q?: string, equipment?: string) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (equipment) params.set("equipment", equipment);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ComponentSummary[]>(`/api/v1/components${suffix}`);
  },

  getSession: (sessionId: string) =>
    request<AssistantResponse>(`/api/v1/sessions/${sessionId}`),

  identify: (sessionId: string, payload: IdentifyPayload) =>
    request<AssistantResponse>(`/api/v1/sessions/${sessionId}/identify`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  confirmLoto: (sessionId: string, confirmedItemIds: string[], note?: string) =>
    request<AssistantResponse>(`/api/v1/sessions/${sessionId}/loto`, {
      method: "POST",
      body: JSON.stringify({
        confirmed_item_ids: confirmedItemIds,
        technician_note: note || null,
      }),
    }),

  step: (sessionId: string, action: "next" | "prev" | "repeat" | "goto", stepIndex?: number) =>
    request<AssistantResponse>(`/api/v1/sessions/${sessionId}/step`, {
      method: "POST",
      body: JSON.stringify({ action, step_index: stepIndex ?? null }),
    }),

  ask: (sessionId: string, transcript: string) =>
    request<AssistantResponse>(`/api/v1/sessions/${sessionId}/ask`, {
      method: "POST",
      body: JSON.stringify({ transcript }),
    }),

  audit: (sessionId: string) =>
    request<{ session_id: string; state: string; entries: AuditEntry[] }>(
      `/api/v1/sessions/${sessionId}/audit`
    ),
};
