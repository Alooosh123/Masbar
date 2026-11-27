export type SessionState =
  | "PENDING_CONFIRMATION"
  | "CREATED"
  | "IDENTIFIED"
  | "AWAITING_LOTO"
  | "READY"
  | "IN_PROGRESS"
  | "COMPLETED";

export type SafetySeverity = "INFO" | "WARNING" | "CRITICAL";

export type IdentificationSource =
  | "MANUAL"
  | "TEXT_SEARCH"
  | "VISION_MOCK"
  | "VISION_VLM";

export interface EquipmentSummary {
  equipment_family: string;
  manufacturer: string;
  component_count: number;
  data_status: string;
}

export interface ComponentSummary {
  part_number: string;
  english_name: string;
  arabic_name: string;
  equipment_models: string[];
  verification_status: string;
}

export interface ChecklistItemState {
  id: string;
  label_ar: string;
  confirmed: boolean;
}

export interface SafetyLockoutProtocol {
  severity: SafetySeverity;
  loto_required: boolean;
  warnings_ar: string[];
  checklist: ChecklistItemState[];
  acknowledged_by_technician: boolean;
  blocked_reason_ar: string | null;
  source_status: "verified" | "unverified";
}

export interface TorqueSpecification {
  value_nm: number;
  value_lbft: number;
  tightening_sequence: string | null;
  verified_from_manual: boolean;
  source_document_id: string;
  source_page: number;
  source_status: string;
}

export interface IdentifiedComponent {
  part_number: string;
  english_name: string;
  arabic_name: string;
  confidence_score: number;
  bounding_box_2d: [number, number, number, number];
  anchor_3d_offset: { x: number; y: number; z: number };
  identification_source: IdentificationSource;
  verification_status: string;
}

export interface ARVisualCue {
  cue_type:
    | "HIGHLIGHT_MESH"
    | "PULL_ARROW"
    | "PUSH_ARROW"
    | "ROTATE_CCW"
    | "ROTATE_CW"
    | "DISCONNECT_PLUG";
  direction: string | null;
  color_hex: string;
  label_ar: string | null;
}

export interface MaintenanceStep {
  step_number: number;
  total_steps: number;
  instruction_ar: string;
  tool_required_ar: string;
  torque_spec: TorqueSpecification | null;
  warning_ar: string | null;
  verification_ar: string | null;
  ar_visual_cue: ARVisualCue;
}

export interface ManualReference {
  document_id: string;
  page_number: number;
  section_title: string;
  verification_status: string;
}

export interface RetrievalCandidate {
  part_number: string;
  arabic_name: string;
  english_name: string;
  score: number;
}

export interface AssistantResponse {
  session_id: string;
  identification_id: string | null;
  state: SessionState;
  equipment_model: string;
  requires_closer_inspection: boolean;
  inspection_prompt_ar: string | null;
  identified_component: IdentifiedComponent | null;
  safety_lockout: SafetyLockoutProtocol | null;
  current_step: MaintenanceStep | null;
  manual_reference: ManualReference | null;
  assistant_message_ar: string;
  next_actions_ar: string[];
  data_disclaimer_ar: string;
  retrieval_candidates: RetrievalCandidate[];
  last_intent: string | null;
  procedure_available: boolean;
  procedure_blocked_reason_ar: string | null;
  abstained: boolean;
  abstention_reason_ar: string | null;
}

export type ChatAction =
  | "open_camera"
  | "close_camera"
  | "start_listening"
  | "stop_listening";

export type ChatSource = "assistant" | "general" | "vision" | "system";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  message?: string;
  image_base64?: string | null;
  session_id?: string | null;
  conversation_id?: string | null;
  history?: ChatTurn[];
  mode?: "auto" | "describe" | "identify";
}

export interface ChatResponse {
  message_ar: string;
  conversation_id?: string | null;
  source: ChatSource;
  action: ChatAction | null;
  session: AssistantResponse | null;
  equipment: EquipmentSummary[];
  components: ComponentSummary[];
  quick_replies: string[];
  abstained: boolean;
  abstention_reason_ar: string | null;
}

export interface HealthResponse {
  status: string;
  app_version: string;
  components: number;
  equipment: number;
  vision_provider: string;
  demo_mode: boolean;
  chat_provider?: string;
  chat_ready?: boolean;
  auth_required?: boolean;
}

export interface AuditEntry {
  id: string;
  timestamp: string;
  event: string;
  detail_ar: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  role: "owner" | "admin" | "technician" | "customer" | "viewer";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  must_change_password: boolean;
}

export interface AuthMeResponse {
  authenticated: boolean;
  user: AuthUser | null;
}


export interface ConversationSummary {
  id: string;
  title: string;
  session_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string;
}

export interface ConversationMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  source: ChatSource | null;
  has_image: boolean;
  created_at: string;
}

export interface ConversationDetail {
  conversation: ConversationSummary;
  messages: ConversationMessage[];
}
