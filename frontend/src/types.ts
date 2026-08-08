export interface ApiError {
  detail?: string;
  agentError?: string;
  voiceError?: string;
  orderId?: number;
}

export interface Clarification {
  itemRef: string;
  field: string;
  question: string;
  candidates: unknown[];
}

export interface OrderItem {
  itemRef: string;
  rawText: string;
  productGuess: string;
  quantity: number | null;
  unit: string;
  status: "resolved" | "ambiguous";
  sku?: string;
  catalogUnit?: string;
  unitPrice?: number | null;
  subtotal?: number | null;
  inStock?: boolean;
  confidence?: number | null;
  ambiguities?: Array<{ field: string; question: string; candidates: unknown[] }>;
}

export interface ErpReceipt {
  erpOrderId: string;
  status: string;
  idempotencyKey: string;
  payload: Record<string, unknown>;
}

export interface OrderVersion {
  versionNumber: number;
  status: string;
  deliveryDate: string | null;
  missingFields: string[];
  evidence: string[];
  total: number | null;
  items: OrderItem[];
  pendingClarification: Clarification | null;
  customerConfirmed: boolean;
  operatorApproved: boolean;
  erpReceipt: ErpReceipt | null;
}

export interface Order {
  id: number;
  state: string;
  conversationId: number;
  customer: { id: number; name: string; phone: string };
  createdAt: string;
  updatedAt: string;
  currentVersion: OrderVersion | null;
}

export interface ToolCall {
  tool: string;
  input: unknown;
  output: unknown;
  success: boolean;
  error?: string;
  at: string;
}

export interface TimelineEvent {
  type: "message" | "agent_run" | "state_transition" | "customer_confirmation" | "operator_approval";
  at: string;
  sender?: string;
  channel?: string;
  content?: string;
  transcription?: string;
  transcriptionConfidence?: number;
  audioUrl?: string;
  agent?: string;
  previousState?: string;
  nextState?: string;
  success?: boolean;
  reason?: string;
  toolCalls?: ToolCall[];
  from?: string;
  to?: string;
  causedBy?: string;
  versionNumber?: number;
  approvedBy?: string;
  notes?: string;
}

export interface Timeline {
  orderId: number;
  events: TimelineEvent[];
}
