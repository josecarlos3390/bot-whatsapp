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

export type AreaUser = {
  username: string;
  display_name: string;
  area: string;
};

export type AuthMe =
  | { kind: "advisor"; advisor: Advisor }
  | { kind: "area"; area: AreaUser };

export type AreaRule = {
  id: string;
  area: string;
  name: string;
  rule_type: string;
  condition: Record<string, unknown>;
  action: Record<string, unknown>;
  priority: number;
  status: "draft" | "published" | "archived";
  version: number;
  created_by?: string;
  updated_at?: string;
};

export type Occasion = {
  id: string;
  name: string;
  slug: string;
  aliases: string[];
  direct: string[];
  exclude: string[];
  exclude_categories: string[];
  bridges: { label: string; terms: string[] }[];
  area: string;
  status: "draft" | "published" | "archived";
  priority: number;
  valid_from?: string | null;
  valid_to?: string | null;
  version: number;
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
  context?: {
    state: {
      intent: string | null;
      category: string | null;
      brand: string | null;
      size: string | null;
      min_price: string | null;
      max_price: string | null;
      last_sku: string | null;
    } | null;
    pending: {
      slot: string | null;
      question: string | null;
      query: string | null;
    } | null;
    last_recommendation: {
      query: string | null;
      category: string | null;
      brand: string | null;
      size: string | null;
      products: { sku: string | null; name: string | null; brand: string | null; price: number | null }[];
      created_at: string | null;
    } | null;
    active_flow: { flow: string; step: number; status: string } | null;
  };
};
