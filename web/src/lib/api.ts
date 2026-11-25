import type {
  AssistantResponse,
  AuditEntry,
  ChatRequest,
  ChatResponse,
  ComponentSummary,
  EquipmentSummary,
  HealthResponse,
} from "../types";

function inferApiUrl(): string {
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  if (configured && configured.trim()) return configured.trim().replace(/\/$/, "");
  if (typeof window !== "undefined") {
    if (import.meta.env.DEV && window.location.hostname) {
      return `http://${window.location.hostname}:8010`;
    }
    return window.location.origin;
  }
  return "http://localhost:8010";
}

export const API_URL = inferApiUrl();
const AUTH_TOKEN_KEY = "masbar.access_token";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: "owner" | "manager" | "engineer" | "technician" | "viewer";
}

export interface AuthStatus {
  auth_enabled: boolean;
  initialized: boolean;
  initial_setup_required: boolean;
}

export interface AuthResult {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
}

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

export function getAuthToken(): string | null {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  window.sessionStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const token = getAuthToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    response = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "تعذر الاتصال بالخادم. تحقق من تشغيل الخادم الخلفي واتصال الواجهة به.",
      0,
      "network_error"
    );
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
  authStatus: () => request<AuthStatus>("/api/v1/auth/status"),

  initializeOwner: (payload: {
    setup_token: string;
    email: string;
    full_name: string;
    password: string;
  }) =>
    request<AuthResult>("/api/v1/auth/initialize", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  login: (email: string, password: string) =>
    request<AuthResult>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () =>
    request<{ authenticated: boolean; user: AuthUser | null }>("/api/v1/auth/me"),

  health: () => request<HealthResponse>("/health"),

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

  createSession: (equipmentModel: string) =>
    request<AssistantResponse>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ equipment_model: equipmentModel }),
    }),

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
