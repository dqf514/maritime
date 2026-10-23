"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { HelpFrame } from "@/components/HelpFrame";
import { PageHeader } from "@/components/PageHeader";
import { VideoDemos } from "@/components/help/VideoDemos";
import { useI18n } from "@/lib/i18n";

import { API_BASE } from "@/lib/api";

/** 视频演示讲解页 —— 内嵌播放器与讲解稿，数据自带，无需拉取文章正文。 */
function VideoDemoArticle() {
  const { t } = useI18n();
  return (
    <HelpFrame>
      <PageHeader
        breadcrumb={[
          { label: t("help.centre", "Knowledge Centre"), href: "/help" },
          { label: t("help.video.title", "Video walkthrough") },
        ]}
        title={t("help.video.title", "Video walkthrough")}
        subtitle={t("help.video.sub", "Narrated product videos with click-to-seek transcripts — full business flow and administrator operations.")}
      />
      <VideoDemos />
      <div className="help-article-actions">
        <Link className="btn" href="/help">
          {t("help.back_list", "All articles")}
        </Link>
      </div>
    </HelpFrame>
  );
}

type Article = {
  slug: string;
  category: string;
  tags: string[];
  title: string;
  summary: string;
  body: string;
};

export default function HelpArticlePage() {
  const { slug } = useParams<{ slug: string }>();
  const { t, locale } = useI18n();

  if (slug === "video-demos") return <VideoDemoArticle />;
  const [art, setArt] = useState<Article | null>(null);
  const [err, setErr] = useState("");
  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";

  useEffect(() => {
    if (!slug) return;
    fetch(`${API_BASE}/api/v1/help/articles/${encodeURIComponent(slug)}?locale=${encodeURIComponent(loc)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("not found");
        return r.json();
      })
      .then(setArt)
      .catch(() => setErr(t("help.article_missing", "Article not found.")));
  }, [slug, loc, t]);

  return (
    <HelpFrame>
      <PageHeader
        breadcrumb={[
          { label: t("help.centre", "Knowledge Centre"), href: "/help" },
          { label: art?.title || slug },
        ]}
        title={art?.title || slug}
      />
      {err ? <p className="flash-err">{err}</p> : null}
      {art ? (
        <article className="help-article">
          <p className="help-summary">{art.summary}</p>
          <div className="help-tags">
            {art.tags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
          <div className="help-body">
            {art.body.split(/\n\n+/).map((para, i) => (
              <p key={i} style={{ whiteSpace: "pre-wrap" }}>
                {para}
              </p>
            ))}
          </div>
          <div className="help-article-actions">
            <Link className="btn" href="/help">
              {t("help.back_list", "All articles")}
            </Link>
            <Link className="btn btn-primary" href="/help?ask=1">
              {t("help.ask_more", "Ask another question")}
            </Link>
          </div>
        </article>
      ) : !err ? (
        <p>{t("common.loading", "Loading…")}</p>
      ) : null}
    </HelpFrame>
  );
}
