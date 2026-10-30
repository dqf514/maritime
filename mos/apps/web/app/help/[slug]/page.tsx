"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { HelpFrame } from "@/components/HelpFrame";
import { PageHeader } from "@/components/PageHeader";
import { DetailRail } from "@/components/masterdetail/DetailRail";
import { MasterDetail } from "@/components/masterdetail/MasterDetail";
import { useDetailRail } from "@/components/masterdetail/useRailItems";
import { StateView } from "@/components/StateView";
import { VideoDemos } from "@/components/help/VideoDemos";
import { useI18n } from "@/lib/i18n";

import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useListBackHref } from "@/lib/listContext";

type Article = {
  slug: string;
  category: string;
  tags: string[];
  title: string;
  summary: string;
  body: string;
};

/** 左栏清单来源 —— 知识中心文章目录。 */
function articleRailSource(loc: string) {
  return {
    endpoint: "/api/v1/help/catalog",
    params: { locale: loc },
    pick: (d: unknown) => ((d as { articles?: Article[] })?.articles ?? []),
    mapRow: (r: Article) => ({
      id: r.slug,
      title: r.title || r.slug,
      meta: [r.category || ""],
      href: `/help/${r.slug}`,
    }),
  };
}

/** 视频演示讲解页 —— 内嵌播放器与讲解稿，数据自带，无需拉取文章正文。 */
function VideoDemoArticle() {
  const { t, locale } = useI18n();
  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
  const backHref = useListBackHref("/help");
  const rail = useDetailRail<Article>(
    articleRailSource(loc),
    {
      id: "video-demos",
      title: t("help.video.title", "Video walkthrough"),
      meta: [],
      href: "/help/video-demos",
    },
  );
  return (
    <HelpFrame
      breadcrumbs={[
        { label: t("help.centre", "Knowledge Centre"), href: backHref },
        { label: t("help.video.title", "Video walkthrough") },
      ]}
    >
      <MasterDetail
        rail={
          <DetailRail
            items={rail.items}
            activeId="video-demos"
            title={t("help.centre", "Knowledge Centre")}
            backHref={backHref}
            backLabel={t("common.back_to_list", { en: "Back to list", zh: "返回列表" })}
            loading={rail.loading}
            error={rail.error}
            onRetry={rail.reload}
          />
        }
        header={
          <PageHeader
            breadcrumb={[
              { label: t("help.centre", "Knowledge Centre"), href: "/help" },
              { label: t("help.video.title", "Video walkthrough") },
            ]}
            title={t("help.video.title", "Video walkthrough")}
            subtitle={t("help.video.sub", "Narrated product videos with click-to-seek transcripts — full business flow and administrator operations.")}
          />
        }
      >
        <VideoDemos />
        <div className="help-article-actions">
          <Link className="btn" href="/help">
            {t("help.back_list", "All articles")}
          </Link>
        </div>
      </MasterDetail>
    </HelpFrame>
  );
}

export default function HelpArticlePage() {
  const { slug } = useParams<{ slug: string }>();
  // 注意：这里必须「先分派、再进子组件」，不能把提前 return 放在本组件的
  // useState/useEffect 之前 —— 否则从 /help/video-demos 客户端跳到别的文章时，
  // 同一组件的 hook 数量会从 1 变成 3，React 直接抛
  // “Rendered more hooks than during the previous render” 整页崩掉。
  if (slug === "video-demos") return <VideoDemoArticle />;
  return <HelpArticle slug={slug} />;
}

function HelpArticle({ slug }: { slug: string }) {
  const { t, locale } = useI18n();
  const [art, setArt] = useState<Article | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const loc = locale?.startsWith("zh") ? "zh-CN" : "en";

  // 左栏：知识中心文章清单（IMOS 式兄弟导航）+「返回列表」
  const backHref = useListBackHref("/help");
  const currentRailItem = useMemo(
    () =>
      art
        ? {
            id: art.slug,
            title: art.title || art.slug,
            meta: [art.category || ""],
            href: `/help/${art.slug}`,
          }
        : null,
    [art],
  );
  const rail = useDetailRail<Article>(
    {
      endpoint: "/api/v1/help/catalog",
      params: { locale: loc },
      pick: (d) => ((d as { articles?: Article[] })?.articles ?? []),
      mapRow: (r) => ({
        id: r.slug,
        title: r.title || r.slug,
        meta: [r.category || ""],
        href: `/help/${r.slug}`,
      }),
    },
    currentRailItem,
  );

  // 统一走 apiGet（带会话），失败要能区分「文章不存在」与「取数失败」（P1-33 / P1-4）。
  const load = useCallback(() => {
    if (!slug) return;
    setLoading(true);
    setErr("");
    apiGet(`/api/v1/help/articles/${encodeURIComponent(slug)}?locale=${encodeURIComponent(loc)}`)
      .then((data: any) => setArt(data as Article))
      .catch((e: any) => {
        setArt(null);
        setErr(
          e?.status === 404
            ? t("help.article_missing", "Article not found.")
            : msgOf(e, t("help.load_fail", "Unable to load knowledge catalogue.")),
        );
      })
      .finally(() => setLoading(false));
  }, [slug, loc, t]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <HelpFrame
      breadcrumbs={[
        { label: t("help.centre", "Knowledge Centre"), href: backHref },
        { label: art?.title || slug },
      ]}
    >
      <MasterDetail
        rail={
          <DetailRail
            items={rail.items}
            activeId={slug}
            title={t("help.centre", "Knowledge Centre")}
            backHref={backHref}
            backLabel={t("common.back_to_list", { en: "Back to list", zh: "返回列表" })}
            loading={rail.loading}
            error={rail.error}
            onRetry={rail.reload}
          />
        }
        header={
          <PageHeader
            breadcrumb={[
              { label: t("help.centre", "Knowledge Centre"), href: "/help" },
              { label: art?.title || slug },
            ]}
            title={art?.title || slug}
          />
        }
      >
        <StateView
          loading={loading}
          error={err || undefined}
          empty={false}
          onRetry={load}
        >
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
          ) : null}
        </StateView>
      </MasterDetail>
    </HelpFrame>
  );
}
