"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export type NotificationItem = {
  id: string;
  title: string;
  body: string | null;
  level: string;
  href: string | null;
  read_at: string | null;
  created_at: string;
};

const POLL_MS = 60_000;

function dotColor(level: string): string {
  const lv = (level || "").toLowerCase();
  if (lv === "critical" || lv === "error" || lv === "danger") return "var(--danger)";
  if (lv === "warning" || lv === "warn") return "var(--warn)";
  if (lv === "success" || lv === "ok") return "var(--ok)";
  return "var(--accent)";
}

export function NotificationBell() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const rows = await apiGet("/api/v1/notifications");
      setItems(Array.isArray(rows) ? rows : []);
      setNow(Date.now());
    } catch {
      // keep last known state — polling retries
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    function onFocus() {
      load();
    }
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const unread = items.filter((n) => !n.read_at).length;
  const recent = items.slice(0, 10);

  function fmtTime(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const diff = (now || d.getTime()) - d.getTime();
    if (diff < 60_000) return t("notify.just_now", "刚刚");
    if (diff < 3_600_000) return t("notify.minutes_ago", "{n} 分钟前", { n: Math.floor(diff / 60_000) });
    if (diff < 86_400_000) return t("notify.hours_ago", "{n} 小时前", { n: Math.floor(diff / 3_600_000) });
    return d.toLocaleDateString(locale.startsWith("zh") ? "zh-CN" : "en-US", {
      month: "2-digit",
      day: "2-digit",
    });
  }

  async function openItem(n: NotificationItem) {
    if (!n.read_at) {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)));
      apiPost(`/api/v1/notifications/${n.id}/read`).catch(() => load());
    }
    if (n.href) {
      setOpen(false);
      router.push(n.href);
    }
  }

  async function readAll() {
    setBusy(true);
    try {
      await apiPost("/api/v1/notifications/read-all");
      const now = new Date().toISOString();
      setItems((prev) => prev.map((x) => ({ ...x, read_at: x.read_at || now })));
    } catch {
      // ignore — next poll resyncs
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="notify-wrap" ref={wrapRef}>
      <button
        type="button"
        className="notify-btn"
        aria-label={t("notify.title", "通知")}
        aria-expanded={open}
        aria-haspopup="menu"
        title={t("notify.title", "通知")}
        onClick={() => {
          setOpen((o) => !o);
          if (!open) load();
        }}
      >
        <svg viewBox="0 0 20 20" width="17" height="17" aria-hidden>
          <path
            fill="currentColor"
            d="M10 2a1 1 0 0 1 1 1v.6A5 5 0 0 1 15 8.4V12l1.3 2.1a.8.8 0 0 1-.68 1.2H4.38a.8.8 0 0 1-.68-1.2L5 12V8.4a5 5 0 0 1 4-4.8V3a1 1 0 0 1 1-1zm-2.2 14.3a2.3 2.3 0 0 0 4.4 0H7.8z"
          />
        </svg>
        {unread > 0 ? (
          <span className="notify-badge" aria-label={t("notify.unread", "{n} 条未读", { n: unread })}>
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="notify-pop" role="menu" aria-label={t("notify.title", "通知")}>
          <div className="notify-pop-head">
            <strong>{t("notify.title", "通知")}</strong>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy || !unread}
              onClick={readAll}
            >
              {t("notify.read_all", "全部已读")}
            </button>
          </div>
          {recent.length ? (
            recent.map((n) => (
              <button
                key={n.id}
                type="button"
                role="menuitem"
                className={`notify-item ${n.read_at ? "" : "unread"}`}
                onClick={() => openItem(n)}
              >
                <span className="notify-dot" style={{ background: dotColor(n.level) }} aria-hidden />
                <span className="notify-item-body">
                  <span className="notify-item-title">{n.title}</span>
                  {n.body ? <span className="notify-item-text">{n.body}</span> : null}
                  <span className="notify-item-time">{fmtTime(n.created_at)}</span>
                </span>
              </button>
            ))
          ) : (
            <p className="notify-empty muted">{t("notify.empty", "暂无通知")}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
