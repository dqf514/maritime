"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { HelpFrame } from "@/components/HelpFrame";
import { useI18n } from "@/lib/i18n";

import { API_BASE } from "@/lib/api";

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
  const focusAsk = params.get("ask") === "1";

  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/help/catalog?locale=${encodeURIComponent(loc)}`)
      .then((r) => r.json())
      .then((data) => {
        setCategories(data.categories || []);
        setArticles(data.articles || []);
      })
      .catch(() => setErr(t("help.load_fail", "Unable to load knowledge catalogue.")));
  }, [loc, t]);

  useEffect(() => {
    if (!q.trim()) {
      setHits(null);
      return;
    }
    const handle = setTimeout(() => {
      fetch(`${API_BASE}/api/v1/help/search?q=${encodeURIComponent(q)}&locale=${encodeURIComponent(loc)}`)
        .then((r) => r.json())
        .then((data) => setHits(data.items || []))
        .catch(() => setHits([]));
    }, 180);
    return () => clearTimeout(handle);
  }, [q, loc]);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`${API_BASE}/api/v1/help/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, locale: loc }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "ask failed");
      setAnswer(data);
    } catch {
      setErr(t("help.ask_fail", "Unable to answer right now. Please try again."));
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
        <h1>{t("help.title", "Knowledge Centre")}</h1>
        <p>{t("help.sub", "Browse guides, search by keyword, or ask a question in plain language.")}</p>
        <input
          className="help-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("help.search_ph", "Search estimates, laytime, Teams, API…")}
          aria-label={t("help.search_ph", "Search")}
        />
      </div>

      {err ? <p className="flash-err">{err}</p> : null}

      <section className={`help-ask-panel ${focusAsk ? "focus" : ""}`} id="ask">
        <h2>{t("help.ask_title", "Ask VoyageOS")}</h2>
        <p className="muted">{t("help.ask_sub", "Examples: How do I connect Teams? Where is voyage P&L?")}</p>
        <form onSubmit={onAsk} className="help-ask-form">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
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
