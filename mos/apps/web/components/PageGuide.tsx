"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StateView } from "@/components/StateView";
import { apiGet, type PageGuide as PageGuideData } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = { pageKey: string };

export function PageGuide({ pageKey }: Props) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PageGuideData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  const isZh = locale.startsWith("zh");
  const pick = (v?: { en: string; zh?: string }) => (v ? (isZh ? v.zh || v.en : v.en) : "");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotFound(false);
    try {
      setData(await apiGet(`/api/v1/guides/${pageKey}`));
    } catch (e: any) {
      setData(null);
      if (e?.status === 404 || e?.detail?.code === "GUIDE_NOT_FOUND") {
        setNotFound(true);
      } else {
        setError(e?.message || t("common.failed", "加载失败"));
      }
    } finally {
      setLoading(false);
    }
  }, [pageKey, t]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function openPanel() {
    setOpen(true);
    if (!data && !loading) load();
  }

  const title = data ? pick(data.title) : t("guide.panel_title", "页面指引");

  return (
    <>
      <button type="button" className="btn btn-ghost btn-sm" onClick={openPanel}>
        ❓ {t("guide.button", "怎么做")}
      </button>
      {open ? (
        <div className="guide-backdrop" role="presentation" onClick={() => setOpen(false)}>
          <aside
            className="guide-panel"
            role="dialog"
            aria-modal="true"
            aria-label={title}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="record-modal-head">
              <h2>{title}</h2>
              <button
                type="button"
                className="icon-btn record-modal-x"
                onClick={() => setOpen(false)}
                aria-label={t("common.close", "关闭")}
              >
                ×
              </button>
            </header>
            <div className="guide-body">
              <StateView
                loading={loading}
                error={error}
                empty={notFound}
                emptyText={t("guide.wip", "该页面指引编写中")}
                onRetry={load}
              >
                {data ? (
                  <>
                    {pick(data.purpose) ? (
                      <section className="guide-section">
                        <h3>{t("guide.purpose", "用途")}</h3>
                        <p className="guide-text">{pick(data.purpose)}</p>
                      </section>
                    ) : null}
                    {data.steps?.length ? (
                      <section className="guide-section">
                        <h3>{t("guide.steps", "标准流程")}</h3>
                        <ol className="guide-steps">
                          {data.steps.map((step, i) => (
                            <li key={i}>
                              <span className="guide-step-no" aria-hidden>
                                {i + 1}
                              </span>
                              <span>{pick(step)}</span>
                            </li>
                          ))}
                        </ol>
                      </section>
                    ) : null}
                    {pick(data.upstream) || pick(data.downstream) ? (
                      <section className="guide-section">
                        <h3>{t("guide.flow", "上下游")}</h3>
                        <div className="guide-flow">
                          {pick(data.upstream) ? (
                            <>
                              <span className="guide-flow-node">{pick(data.upstream)}</span>
                              <span className="guide-flow-arrow" aria-hidden>
                                →
                              </span>
                            </>
                          ) : null}
                          <span className="guide-flow-node current">{t("guide.current_page", "本页")}</span>
                          {pick(data.downstream) ? (
                            <>
                              <span className="guide-flow-arrow" aria-hidden>
                                →
                              </span>
                              <span className="guide-flow-node">{pick(data.downstream)}</span>
                            </>
                          ) : null}
                        </div>
                      </section>
                    ) : null}
                    {pick(data.roles) ? (
                      <section className="guide-section">
                        <h3>{t("guide.roles", "适用岗位")}</h3>
                        <p className="guide-text">{pick(data.roles)}</p>
                      </section>
                    ) : null}
                    {data.help_slugs?.length ? (
                      <section className="guide-section">
                        <h3>{t("guide.more", "延伸阅读")}</h3>
                        <div className="guide-links">
                          {data.help_slugs.map((slug) => (
                            <Link key={slug} href={`/help/${slug}`} className="guide-link">
                              {slug}
                            </Link>
                          ))}
                        </div>
                      </section>
                    ) : null}
                  </>
                ) : null}
              </StateView>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
