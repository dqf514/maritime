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

export { API_BASE };
