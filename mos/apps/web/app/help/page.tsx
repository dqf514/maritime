"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { HelpFrame } from "@/components/HelpFrame";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { useI18n } from "@/lib/i18n";

import { apiGet, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";

type Cat = { id: string; label: string };
type Article = { slug: string; category: string; tags: string[]; title: string; summary: string };

function HelpHomePage() {
  const { t, locale } = useI18n();
  const params = useSearchParams();
  const [categories, setCategories] = useState<Cat[]>([]);
  const [articles, setArticles] = useState<Article[]>([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Article[] | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ answer: string; related?: Article[]; confidence?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // 目录取数状态：失败要显示错误态，而不是「空知识库」（P1-33 / P1-4）。
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [searchErr, setSearchErr] = useState("");
  const focusAsk = params.get("ask") === "1";

  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";

  // 统一走 apiGet：带 credentials:"include" + Bearer 回退，
  // 否则裸 fetch 认不出会话 → 登录用户看到空知识库（P1-33）。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadErr("");
    apiGet(`/api/v1/help/catalog?locale=${encodeURIComponent(loc)}`)
      .then((data: any) => {
        if (cancelled) return;
        setCategories(data?.categories || []);
        setArticles(data?.articles || []);
      })
      .catch((e) => {
        if (cancelled) return;
        setCategories([]);
        setArticles([]);
        setLoadErr(msgOf(e, t("help.load_fail", "Unable to load knowledge catalogue.")));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loc, t]);

  useEffect(() => {
    if (!q.trim()) {
      setHits(null);
      setSearchErr("");
      return;
    }
    let cancelled = false;
    const handle = setTimeout(() => {
      apiGet(`/api/v1/help/search?q=${encodeURIComponent(q)}&locale=${encodeURIComponent(loc)}`)
        .then((data: any) => {
          if (cancelled) return;
          setHits(data?.items || []);
          setSearchErr("");
        })
        .catch((e) => {
          if (cancelled) return;
          setHits(null);
          setSearchErr(msgOf(e, t("help.search_fail", "Search failed — please try again.")));
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [q, loc, t]);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const data = await apiPost("/api/v1/help/ask", { question, locale: loc });
      setAnswer(data);
    } catch (ex) {
      setErr(msgOf(ex, t("help.ask_fail", "Unable to answer right now. Please try again.")));
    } finally {
      setBusy(false);
    }
  }

  const byCat = useMemo(() => {
    const map: Record<string, Article[]> = {};
    for (const a of articles) {
      (map[a.category] ||= []).push(a);
    }
    return map;
  }, [articles]);

  const list = hits ?? articles;

  return (
    <HelpFrame>
      <div className="help-hero">
        <PageHeader
          breadcrumb={[{ label: t("nav.help", "Knowledge Centre") }]}
          title={t("help.title", "Knowledge Centre")}
          subtitle={t("help.sub", "Browse guides, search by keyword, or ask a question in plain language.")}
        />
        <input
          className="help-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("help.search_ph", "Search estimates, laytime, Teams, API…")}
          aria-label={t("help.search_ph", "Search")}
        />
        <Link className="help-feature" href="/help/video-demos">
          <span className="help-feature-badge">{t("help.video.badge", "Video")}</span>
          <span className="help-feature-title">{t("help.video.title", "Video walkthrough")}</span>
          <span className="help-feature-sub">
            {t("help.video.featured_sub", "Narrated product videos with click-to-seek transcripts — business flow & administrator operations.")}
          </span>
        </Link>
      </div>

      {err ? <p className="flash-err">{err}</p> : null}

      <section className={`help-ask-panel ${focusAsk ? "focus" : ""}`} id="ask">
        <h2>{t("help.ask_title", "Ask MariOS")}</h2>
        <p className="muted">{t("help.ask_sub", "Examples: How do I connect Teams? Where is voyage P&L?")}</p>
        <form onSubmit={onAsk} className="help-ask-form">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label={t("help.ask_ph", "Type your question…")}
            placeholder={t("help.ask_ph", "Type your question…")}
            autoFocus={focusAsk}
          />
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? t("common.loading", "Loading…") : t("help.ask_btn", "Ask")}
          </button>
        </form>
        {answer ? (
          <div className="help-answer">
            <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer}</p>
            {answer.related && answer.related.length > 0 ? (
              <div className="help-related">
                <strong>{t("help.related", "Related articles")}</strong>
                <ul>
                  {answer.related.map((r) => (
                    <li key={r.slug}>
                      <Link href={`/help/${r.slug}`}>{r.title}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <div className="help-layout">
        <aside className="help-cats">
          <h3>{t("help.categories", "Categories")}</h3>
          <ul>
            <li>
              <a href="#all">{t("help.all", "All")}</a>
            </li>
            {categories.map((c) => (
              <li key={c.id}>
                <a href={`#cat-${c.id}`}>{c.label}</a>
              </li>
            ))}
          </ul>
        </aside>

        <div className="help-list" id="all">
          {searchErr ? <p className="flash-err">{searchErr}</p> : null}
          <StateView
            loading={loading}
            error={loadErr || undefined}
            empty={!loadErr && !searchErr && !list.length}
            emptyText={t("help.empty", "No articles in the knowledge centre yet.")}
            onRetry={() => {
              setLoading(true);
              setLoadErr("");
              apiGet(`/api/v1/help/catalog?locale=${encodeURIComponent(loc)}`)
                .then((data: any) => {
                  setCategories(data?.categories || []);
                  setArticles(data?.articles || []);
                })
                .catch((e) => setLoadErr(msgOf(e, t("help.load_fail", "Unable to load knowledge catalogue."))))
                .finally(() => setLoading(false));
            }}
          >
            {hits ? (
              <section>
                <h2>{t("help.results", "Search results")} ({list.length})</h2>
                <div className="help-cards">
                  {list.map((a) => (
                    <Link key={a.slug} href={`/help/${a.slug}`} className="help-card">
                      <h3>{a.title}</h3>
                      <p>{a.summary}</p>
                    </Link>
                  ))}
                </div>
                {list.length === 0 ? <p className="muted">{t("help.no_results", "No articles matched.")}</p> : null}
              </section>
            ) : (
              categories.map((c) => (
                <section key={c.id} id={`cat-${c.id}`}>
                  <h2>{c.label}</h2>
                  <div className="help-cards">
                    {(byCat[c.id] || []).map((a) => (
                      <Link key={a.slug} href={`/help/${a.slug}`} className="help-card">
                        <h3>{a.title}</h3>
                        <p>{a.summary}</p>
                      </Link>
                    ))}
                  </div>
                </section>
              ))
            )}
          </StateView>
        </div>
      </div>
    </HelpFrame>
  );
}

export default function HelpHomePageWrapper() {
  return (
    <Suspense>
      <HelpHomePage />
    </Suspense>
  );
}
