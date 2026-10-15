// Thin client for the Campus Customs back-office API (backend/main.py).

export const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";
export const AGENTS: AgentName[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];

export type TicketStatus = "open" | "in_progress" | "waiting_approval" | "resolved";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: TicketStatus;
  created_at: string;
  resolved: boolean;
}

export interface ActivityEvent {
  seq: number;
  time: string;
  agent: AgentName | "harness" | "human";
  ticket_id: number | null;
  type: "said" | "tool_call" | "guard_block" | "delegation" | "agent_start" | "run_start" | "run_end" | "error" | "human_action";
  text?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  result?: unknown;
  output?: Record<string, unknown>;
}

export interface AgentSummary {
  tools_used: string[];
  said: string[];
  blocked: number;
}

export interface Activity {
  run_id: string | null;
  recent_runs: string[];
  finished?: boolean;
  tokens_used?: number | null;
  last_seq?: number;
  agents: Partial<Record<AgentName, AgentSummary>>;
  events: ActivityEvent[];
}

export interface Approval {
  id: number;
  ticket_id: number;
  kind: "invoice_payment" | "rent_payment" | "purchase" | "price_override";
  ref_id: number | null;
  sku: string | null;
  qty: number | null;
  amount: number;
  details: string;
  requested_by: string;
  status: string;
  created_at: string;
}

export interface Cash {
  accounts: { name: string; balance: number; date: string }[];
  total: number;
}

export interface TicketOutcome {
  ticket_id: number;
  handled_by: AgentName[];
  status: TicketStatus;
  summary: string;
  human_action_needed: string | null;
}

export interface RunResult {
  run_id: string;
  status: string;
  report: { run_summary: string; tickets: TicketOutcome[] } | null;
  tokens_used: number;
  delegations_used: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? body));
  }
  return body as T;
}

export const api = {
  tickets: () => request<{ resolved: number; unresolved: number; tickets: Ticket[] }>("/tickets"),
  run: (ticketId: number) => request<RunResult>(`/tickets/${ticketId}/run`, { method: "POST" }),
  activity: (params: { run_id?: string; since_seq?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.run_id) q.set("run_id", params.run_id);
    if (params.since_seq) q.set("since_seq", String(params.since_seq));
    return request<Activity>(`/activity${q.size ? `?${q}` : ""}`);
  },
  approvals: () => request<Approval[]>("/approvals"),
  approve: (id: number, approvedBy: string) =>
    request<{ checking_after: number; ticket_status: TicketStatus }>(`/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy }),
    }),
  cash: () => request<Cash>("/cash"),
  reset: () => request<{ reset: boolean }>("/reset", { method: "POST" }),
};

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

export const AGENT_INFO: Record<AgentName, { title: string; role: string; color: string }> = {
  boss: { title: "The Boss", role: "Operations lead", color: "#f2c94c" },
  inventory: { title: "Inventory", role: "Stock & restock", color: "#5fb4ff" },
  accounting: { title: "Accounting", role: "Bills & approvals", color: "#6fcf97" },
  facilities: { title: "Facilities", role: "Lease & landlord", color: "#f2994a" },
  customer_service: { title: "Customer Service", role: "The shop's voice", color: "#ef7fbf" },
};
