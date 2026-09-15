const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type Me = {
  user: { id: string; email: string; full_name: string | null; locale: string | null; roles: string[] };
  tenant: {
    id: string;
    name: string;
    code: string;
    status: string;
    default_locale: string;
    default_timezone: string;
    profile_tier: string;
  };
  licensed_modules: string[];
};

export type SearchHit = {
  id: string;
  title: string;
  keywords: string[];
  module: string;
  href?: string | null;
  action?: string | null;
};

function authHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  // LEGACY fallback: the session now lives in an HttpOnly cookie sent via
  // credentials:"include". This localStorage Bearer path only serves sessions
  // created before the cookie migration — safe to remove once those expire.
  const token = localStorage.getItem("voyageos_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(res: Response) {
  if (res.status !== 401 || typeof window === "undefined") return;
  localStorage.removeItem("voyageos_token");
  if (!window.location.pathname.startsWith("/login")) {
    window.location.href = "/login";
  }
}

export function generateTempPassword(length = 16): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%&*";
  const buf = new Uint32Array(length);
  crypto.getRandomValues(buf);
  let out = "";
  for (const n of buf) out += chars[n % chars.length];
  return out;
}

export async function apiLogin(email: string, password: string, tenant_code = "demo") {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    credentials: "include", // server plants the HttpOnly session cookie
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, tenant_code }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err: any = new Error("Login failed");
    err.detail = body?.detail;
    err.code = body?.detail?.code;
    throw err;
  }
  // access_token is still returned for backward compatibility; callers must
  // NOT persist it — the cookie is the session.
  return res.json() as Promise<{ access_token: string }>;
}

export async function apiLogout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/v1/auth/logout`, { method: "POST", credentials: "include" });
  } catch {
    // best-effort: local cleanup proceeds even if the API is unreachable
  }
}

export async function apiMe(): Promise<Me> {
  const res = await fetch(`${API_BASE}/api/v1/me`, { headers: { ...authHeaders() }, credentials: "include" });
  if (!res.ok) throw new Error("Unauthorized");
  return res.json();
}

export async function apiSearch(q: string): Promise<SearchHit[]> {
  const res = await fetch(`${API_BASE}/api/v1/search?q=${encodeURIComponent(q)}`, {
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) return [];
  return res.json();
}

export async function apiRunSelfCheck() {
  const res = await fetch(`${API_BASE}/api/v1/settings/selfcheck/run`, {
    method: "POST",
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("SelfCheck failed");
  return res.json();
}

export async function apiCreateBackup() {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/backups`, {
    method: "POST",
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("Backup failed");
  return res.json();
}

export async function apiListBackups() {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/backups`, {
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("List backups failed");
  return res.json();
}

export async function apiCreateMigration(note?: string) {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/migrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include",
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error("Create migration failed");
  return res.json();
}

export async function apiAddMigrationSource(jobId: string, source_type: string) {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/migrations/${jobId}/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include",
    body: JSON.stringify({ source_type, config: {} }),
  });
  if (!res.ok) throw new Error("Add source failed");
  return res.json();
}

export async function apiRunAnalyze(jobId: string) {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/migrations/${jobId}/run-analyze`, {
    method: "POST",
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("Analyze failed");
  return res.json();
}

export async function apiListProposals(jobId: string) {
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/migrations/${jobId}/proposals`, {
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("List proposals failed");
  return res.json();
}

export async function apiListLicenses() {
  const res = await fetch(`${API_BASE}/api/v1/tenants/current/licenses`, {
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) throw new Error("Licenses failed");
  return res.json();
}

export async function apiGet(path: string) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { ...authHeaders() }, credentials: "include" });
  if (!res.ok) {
    handleUnauthorized(res);
    const body = await res.json().catch(() => ({}));
    const err: any = new Error(typeof body?.detail === "string" ? body.detail : body?.detail?.message || `GET ${path} failed`);
    err.status = res.status;
    err.detail = body?.detail;
    throw err;
  }
  return res.json();
}

export async function apiPost(path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    handleUnauthorized(res);
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `POST ${path} failed`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return res.json();
}

export async function apiPut(path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    handleUnauthorized(res);
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `PUT ${path} failed`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return res.json();
}

export async function apiPatch(path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    handleUnauthorized(res);
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `PATCH ${path} failed`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return res.json();
}

export async function apiDelete(path: string) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { ...authHeaders() },
    credentials: "include",
  });
  if (!res.ok) {
    handleUnauthorized(res);
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `DELETE ${path} failed`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return res.json().catch(() => ({ ok: true }));
}

export async function apiCommitMigration(jobId: string, proposal_ids: string[]) {
  return apiPost(`/api/v1/settings/dataops/migrations/${jobId}/commit`, { proposal_ids });
}

export async function apiUpload(path: string, form: FormData) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { ...authHeaders() },
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    handleUnauthorized(res);
    const data = await res.json().catch(() => ({}));
    const err: any = new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || data?.detail?.code || `POST ${path} failed`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return res.json();
}

export async function apiUploadMigrationExcel(jobId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/settings/dataops/migrations/${jobId}/upload-excel`, {
    method: "POST",
    headers: { ...authHeaders() },
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw new Error("Excel upload failed");
  return res.json();
}

export type TaskOut = {
  id: string;
  title: string;
  description: string | null;
  status: "todo" | "in_progress" | "done" | "cancelled";
  priority: "low" | "normal" | "high" | "urgent";
  due_at: string | null;
  assignee: { id: string; email: string; full_name: string | null } | null;
  created_by: string | null;
  entity_type: string | null;
  entity_id: string | null;
  source: string | null;
  completed_at: string | null;
  created_at: string;
};

export type TaskAssignee = { id: string; email: string; full_name: string | null };

export type HomeSummary = {
  tasks: { open: number; overdue: number; due_today: number; items: TaskOut[] };
  notifications: { unread: number; items: unknown[] };
  approvals: { count: number; items: { title?: string; href?: string }[] };
  alerts: { kind: string; title: string; detail: string; href: string; severity: string; due_in_days: number | null }[];
  schedule: { kind: string; title: string; subtitle: string; start: string; href: string }[];
  kpis: { key: string; label: { en: string; zh?: string }; value: string; hint?: string; href?: string }[];
  exceptions?: { critical: number; warning: number };
};

export type ExceptionKind =
  | "pnl_deterioration"
  | "eta_delay"
  | "demurrage_open"
  | "claim_timebar"
  | "invoice_overdue"
  | "cert_expired"
  | "cert_expiring"
  | "off_hire_open"
  | "tc_redelivery_due"
  | "sanctions_blocked"
  | "dq_issue";

export type ExceptionItem = {
  kind: ExceptionKind;
  severity: "critical" | "warning";
  title: string;
  detail: string;
  value: string;
  entity_type: string;
  entity_id: string;
  href: string;
  detected_at: string;
};

export type ExceptionScan = {
  summary: { critical: number; warning: number; total: number };
  items: ExceptionItem[];
};

export type VoyageLifecycleStep = {
  key: "estimate" | "charter" | "execution" | "laytime" | "invoicing" | "settlement" | "closed";
  label: { en: string; zh?: string };
  state: "done" | "current" | "todo";
  href?: string | null;
  detail?: string | null;
};

export type VoyagePnlLine = {
  key: "revenue" | "hire" | "demurrage" | "port_costs" | "canal" | "bunker" | "commission" | "emissions" | "other";
  estimated: number | null;
  actual: number | null;
  variance: number | null;
};

export type VoyageOverviewPortCall = {
  id: string;
  seq?: number;
  purpose?: string | null;
  port_id?: string | null;
  port_name?: string | null;
  eta?: string | null;
  ata?: string | null;
  etd?: string | null;
  atd?: string | null;
};

export type VoyageOverview = {
  voyage: {
    id: string;
    voyage_no?: string | null;
    status: string;
    vessel_id: string | null;
    vessel_name: string | null;
    charter_id: string | null;
    cp_date: string | null;
    started_at: string | null;
    completed_at: string | null;
  };
  charter: {
    id: string;
    charter_no: string;
    charter_type: string;
    status: string;
    counterparty_name: string | null;
    estimate_id: string | null;
  } | null;
  estimate: {
    id: string;
    status: string;
    results_summary: { total_revenue: number | null; voyage_cost: number | null; tce: number | null } | null;
  } | null;
  lifecycle: VoyageLifecycleStep[];
  port_calls: VoyageOverviewPortCall[];
  noon_reports_count: number;
  laytime: { id: string; status: string; result_type: string | null; amount: number | null; currency: string | null }[];
  claims: { id: string; claim_no?: string | null; status?: string | null; amount?: number | null; currency?: string | null }[];
  invoices: { id: string; invoice_no?: string | null; status?: string | null; amount?: number | null; currency?: string | null }[];
  off_hire: { id: string; start_at?: string | null; end_at?: string | null; reason?: string | null; deducted_days?: number | null }[];
  pnl: {
    estimated_pnl: number | null;
    actual_pnl: number | null;
    variance_pnl: number | null;
    currency: string;
    lines: VoyagePnlLine[];
  };
};

export type PageGuide = {
  page_key: string;
  title: { en: string; zh?: string };
  purpose: { en: string; zh?: string };
  steps: { en: string; zh?: string }[];
  upstream: { en: string; zh?: string };
  downstream: { en: string; zh?: string };
  roles: { en: string; zh?: string };
  help_slugs: string[];
};

export type OnboardingItem = {
  key: string;
  label: { en: string; zh?: string };
  hint: { en: string; zh?: string };
  done: boolean;
  href: string;
};

export type OnboardingState = {
  items: OnboardingItem[];
  progress: { done: number; total: number };
  dismissed: boolean;
};

export { API_BASE };
