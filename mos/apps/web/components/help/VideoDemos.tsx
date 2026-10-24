"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Tabs } from "@/components/Tabs";
import { useI18n } from "@/lib/i18n";
import { VIDEO_DEMOS, type VideoDemoId } from "@/lib/video-demos";

const TAB_ORDER: VideoDemoId[] = ["business-zh", "business-en", "admin-zh"];

const TAB_KEYS: Record<VideoDemoId, string> = {
  "business-zh": "help.video.tab_business_zh",
  "business-en": "help.video.tab_business_en",
  "admin-zh": "help.video.tab_admin_zh",
};

const TAB_FALLBACKS: Record<VideoDemoId, string> = {
  "business-zh": "Business demo · Chinese narration",
  "business-en": "Business demo · English narration",
  "admin-zh": "Admin operations · Chinese narration",
};

function fmtClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** 知识中心「视频演示讲解」——内嵌播放器 + 可点击跳转的完整讲解稿。 */
export function VideoDemos() {
  const { t, locale } = useI18n();
  const defaultId: VideoDemoId = locale?.startsWith("zh") ? "business-zh" : "business-en";
  const [activeId, setActiveId] = useState<VideoDemoId>(defaultId);
  const [currentTime, setCurrentTime] = useState(0);
  const [failed, setFailed] = useState(false);
  /** 自动播放被浏览器拦截（不是取数失败）——给出可见提示 */
  const [playBlocked, setPlayBlocked] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const demo = VIDEO_DEMOS[activeId];

  // 切换视频时复位时间轴与错误态
  useEffect(() => {
    setCurrentTime(0);
    setFailed(false);
  }, [activeId]);

  const activeChapter = useMemo(() => {
    let found = demo.chapters[0];
    for (const ch of demo.chapters) {
      if (currentTime + 0.25 >= ch.start) found = ch;
    }
    return found;
  }, [demo, currentTime]);

  function seek(sec: number) {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = sec;
    // 用户点击章节/讲解行即视为想看该段——静音失败（自动播放策略）不影响页面
    v.play().catch(() => setPlayBlocked(true));
  }

  return (
    <div className="vd-root">
      <Tabs
        variant="pill"
        items={TAB_ORDER.map((id) => ({ key: id, label: t(TAB_KEYS[id], TAB_FALLBACKS[id]) }))}
        value={activeId}
        onChange={(key) => setActiveId(key as VideoDemoId)}
        aria-label={t("help.video.title", "Video walkthrough")}
        className="vd-tabs"
      />

      <div className="vd-player">
        {failed ? (
          <p className="vd-failed">{t("help.video.load_fail", "Unable to load the video. The transcript below is still available.")}</p>
        ) : (
          <video
            key={activeId}
            ref={videoRef}
            src={demo.src}
            controls
            preload="metadata"
            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
            onError={() => setFailed(true)}
            onPlay={() => setPlayBlocked(false)}
          />
        )}
        {playBlocked ? (
          <p className="vd-hint" role="status">
            {t("help.video.play_blocked", "Playback was blocked by the browser — press the play button to start the video.")}
          </p>
        ) : null}
        <p className="vd-hint">
          {t("help.video.seek_hint", "Click any chapter or transcript line to jump to that moment.")}{" "}
          <a href={demo.srt} download>
            {t("help.video.srt_link", "Download subtitles (.srt)")}
          </a>
          <span className="vd-meta">
            {fmtClock(demo.duration)} · {demo.chapters.length} {t("help.video.chapters_word", "chapters")}
          </span>
        </p>
      </div>

      <div className="vd-layout">
        <aside className="vd-chapters">
          <h3>{t("help.video.chapters", "Chapters")}</h3>
          <ul>
            {demo.chapters.map((ch) => (
              <li key={ch.id}>
                <button
                  type="button"
                  className={`vd-chapter${ch.id === activeChapter.id ? " on" : ""}`}
                  onClick={() => seek(ch.start)}
                >
                  <span className="vd-chapter-time">{ch.startLabel}</span>
                  <span className="vd-chapter-title">{ch.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="vd-transcript">
          <h3>{t("help.video.transcript", "Transcript")}</h3>
          {demo.chapters.map((ch) => (
            <section key={ch.id} className={`vd-cue-chapter${ch.id === activeChapter.id ? " on" : ""}`} id={`vd-${activeId}-${ch.id}`}>
              <h4>
                <button type="button" className="vd-cue-btn" onClick={() => seek(ch.start)}>
                  {ch.startLabel}
                </button>
                {ch.title}
              </h4>
              {ch.cues.map((cue) => (
                <p key={`${ch.id}-${cue.t}`} className="vd-cue">
                  <button type="button" className="vd-cue-btn" onClick={() => seek(cue.t)} title={t("help.video.seek_hint", "Jump to this moment")}>
                    {fmtClock(cue.t)}
                  </button>
                  <span className="vd-cue-text">{cue.tts}</span>
                </p>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
