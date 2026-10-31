"use client";

/**
 * 操作日志弹窗 —— 工作台「最近活动」的完整视图。
 *
 * 首屏只给 8 条动态，主人在日志里找一条两个月的记录就得翻页 —— 这里给全量：
 *   * 分页（每页 25 条，服务端 offset 分页 + total）
 *   * 关键字筛选（动作码 / 实体 / 操作人 / 明文，按 300ms 去抖）
 *   * 全屏（顶栏一键铺满视口 —— 日志表列多，窄弹窗读不清）
 *
 * 无内联样式（一致性基线），颜色只用主题 token。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { formatInTz, parseUtc } from "@/lib/datetime";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

export type ActivityItem = {
  id: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  module: string | null;
  actor: string | null;
  href: string | null;
  created_at: string | null;
};

/** 审计动作码 → 展示文案（去掉 action 前缀域，如 voyage.update → update） */
export function actionLabel(action: string): string {
  const a = action || "";
  const dot = a.lastIndexOf(".");
  return dot >= 0 ? a.slice(dot + 1) : a;
}

const PAGE_SIZE = 25;

/**
 * 由父组件按需挂载（open 时才渲染）—— 每次打开都是干净状态，
 * 不用在 effect 里重置一堆 state。
 */
export function ActivityLogModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [full, setFull] = useState(false);
  /** 输入框里的即时值（未去抖） */
  const [kw, setKw] = useState("");
  /** 已提交到服务端的查询词 */
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  /** null = 还在加载（首屏与翻页/筛选切换时） */
  const [rows, setRows] = useState<ActivityItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  /** 已提交给服务端的查询词（用来判断"这次输入有没有真的改变查询"） */
  const submittedRef = useRef("");

  const loading = rows === null;

  // 关键字去抖 —— 每敲一个字就查一次太吵。
  // 注意：查询词没变时**不能**重置列表 —— 否则挂载后那次首屏结果会被
  // 300ms 后的定时器清成「加载中」，且因为查询词没变而不会重新拉取。
  useEffect(() => {
    const id = setTimeout(() => {
      const next = kw.trim();
      if (next === submittedRef.current) return;
      submittedRef.current = next;
      setQuery(next);
      setPage(0);
      setRows(null);
    }, 300);
    return () => clearTimeout(id);
  }, [kw]);

  useEffect(() => {
    let cancelled = false;
    const qs = new URLSearchParams();
    qs.set("limit", String(PAGE_SIZE));
    qs.set("offset", String(page * PAGE_SIZE));
    if (query) qs.set("q", query);
    apiGet(`/api/v1/activity/feed?${qs.toString()}`).then(
      (data) => {
        if (cancelled) return;
        const items = Array.isArray(data?.items) ? (data.items as ActivityItem[]) : [];
        setRows(items);
        setTotal(Number(data?.total ?? items.length));
        setErr(null);
      },
      (ex) => {
        if (cancelled) return;
        setRows([]);
        setTotal(0);
        setErr(
          t("page.home.activity_load_fail", "Activity could not be loaded: {err}", {
            err: msgOf(ex),
          }),
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, [page, query, t]);

  // ESC 关闭 + 打开时把焦点送进搜索框
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    const id = setTimeout(() => searchRef.current?.focus(), 30);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(id);
    };
  }, [onClose]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const range = useMemo(() => {
    if (!total) return { from: 0, to: 0 };
    return { from: page * PAGE_SIZE + 1, to: Math.min(total, (page + 1) * PAGE_SIZE) };
  }, [page, total]);

  const title = t("page.home.activity_log", "Activity log");
  const fsLabel = full ? t("common.exit_fullscreen", "Exit full screen") : t("common.fullscreen", "Full screen");
  const list = rows || [];

  return (
    <div className="activity-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className={`activity-modal${full ? " activity-modal-full" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="activity-modal-head">
          <h2>{title}</h2>
          <div className="activity-modal-head-actions">
            <button
              type="button"
              className="icon-btn activity-modal-fs"
              onClick={() => setFull((v) => !v)}
              aria-label={fsLabel}
              title={fsLabel}
              aria-pressed={full}
            >
              {full ? "⤡" : "⤢"}
            </button>
            <button
              type="button"
              className="icon-btn activity-modal-x"
              onClick={onClose}
              aria-label={t("common.close", "Close")}
              title={t("common.close", "Close")}
            >
              ×
            </button>
          </div>
        </header>

        <div className="activity-modal-toolbar">
          <input
            ref={searchRef}
            type="search"
            className="activity-modal-search"
            placeholder={t("page.home.activity_search_ph", "Search activity by keyword…")}
            aria-label={t("page.home.activity_search_label", "Keyword")}
            value={kw}
            onChange={(e) => setKw(e.target.value)}
          />
          {kw ? (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setKw("")}>
              {t("common.clear", "Clear")}
            </button>
          ) : null}
          <span className="muted activity-modal-total">
            {t("page.home.activity_total", "{n} records", { n: total })}
          </span>
        </div>

        <div className="activity-modal-body">
          {err ? (
            <div className="wb-empty activity-modal-err" role="alert">
              {err}
            </div>
          ) : null}
          {loading ? <div className="wb-empty">{t("common.loading", "Loading…")}</div> : null}
          {!loading && !err && !list.length ? (
            <div className="wb-empty">
              {query
                ? t("page.home.activity_empty", "No activity matches this keyword")
                : t("page.home.no_activity", "No recent activity")}
            </div>
          ) : null}
          {list.length ? (
            <table className="table activity-modal-table">
              <thead>
                <tr>
                  <th>{t("page.home.activity_time", "Time")}</th>
                  <th>{t("page.home.activity_actor", "Actor")}</th>
                  <th>{t("page.home.activity_action", "Action")}</th>
                  <th>{t("page.home.activity_entity", "Entity")}</th>
                </tr>
              </thead>
              <tbody>
                {list.map((a) => {
                  const d = parseUtc(a.created_at);
                  const when = d
                    ? formatInTz(d, null, {
                        year: undefined,
                        month: "2-digit",
                        day: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "—";
                  const entity = [a.entity_type, a.entity_id].filter(Boolean).join(" ");
                  return (
                    <tr key={a.id}>
                      <td className="activity-modal-when">{when}</td>
                      <td>{a.actor || t("page.home.someone", "Someone")}</td>
                      <td>
                        <span className="wb-activity-action">{actionLabel(a.action)}</span>
                        <span className="muted activity-modal-action-full">{a.action}</span>
                      </td>
                      <td className="activity-modal-entity">
                        {a.href ? (
                          <Link href={a.href} className="row-link">
                            {entity || a.module || "—"}
                          </Link>
                        ) : (
                          entity || a.module || "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </div>

        <footer className="activity-modal-foot">
          <span className="muted">
            {t("page.home.activity_range", "{from}–{to} of {n}", {
              from: range.from,
              to: range.to,
              n: total,
            })}
          </span>
          <div className="activity-modal-pager">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page === 0 || loading}
              onClick={() => {
                setPage((p) => Math.max(0, p - 1));
                setRows(null);
              }}
            >
              ← {t("common.prev_page", "Previous")}
            </button>
            <span className="muted">
              {t("common.page_no", "Page {n} / {total}", { n: page + 1, total: pageCount })}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={page + 1 >= pageCount || loading}
              onClick={() => {
                setPage((p) => p + 1);
                setRows(null);
              }}
            >
              {t("common.next_page", "Next")} →
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
