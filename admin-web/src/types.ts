export type Advisor = {
  username: string;
  display_name: string;
  is_admin: boolean;
  is_supervisor?: boolean;
  role?: "admin" | "supervisor" | "agent";
  on_duty: boolean;
  active?: boolean;
  id?: string;
};

export type AdvisorMetric = {
  username: string;
  advisor: string;
  taken: number;
  resolved: number;
  reopened: number;
  replies: number;
  avg_response_minutes: number | null;
  avg_resolution_minutes: number | null;
};

export type Handoff = {
  id: string;
  status: "pending" | "taken" | "resolved" | "returned";
  reason: string | null;
  assigned_to: string | null;
  waiting_minutes: number;
  sla_minutes: number;
  overdue: boolean;
  sla_paused?: boolean;
  resolution_category?: string | null;
  contact: string;
  wa_id: string;
  unread?: boolean;
  conversation_id: string;
};

export type Message = {
  id: string;
  direction: "in" | "out";
  type: string;
  text: string | null;
  payload?: { filename?: string; mime_type?: string; media?: { media_id?: string; mime_type?: string; filename?: string; kind?: string } };
  created_at: string | null;
};

export type HandoffDetail = Handoff & {
  contact: { wa_id: string; name: string | null; phone: string | null };
  profile: { city: string | null; preferred_store: string | null };
  orders: { number: string; status: string; total: string; created_at: string | null }[];
  cart: { count: number; total: string; items: { name: string; quantity: number }[] } | null;
  events: { advisor: string | null; action: string; detail: string | null; created_at: string | null }[];
  notes: { id: string; advisor: string; text: string; created_at: string | null }[];
  messages: Message[];
  unread: boolean;
  can_take: boolean;
  can_reply: boolean;
  can_resolve: boolean;
  can_transfer: boolean;
  can_reopen: boolean;
  resolution_category: string | null;
  sla_paused: boolean;
  bot_paused: boolean;
};
